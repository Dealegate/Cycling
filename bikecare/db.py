"""SQLite storage.  One file, no migrations framework: the schema is created on
open and new columns are added by ``_migrate`` when an older file turns up."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import catalog

SCHEMA = """
CREATE TABLE IF NOT EXISTS bikes (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    frame          TEXT NOT NULL DEFAULT 'road',
    strava_gear_id TEXT UNIQUE,
    notes          TEXT NOT NULL DEFAULT '',
    retired        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS components (
    id             INTEGER PRIMARY KEY,
    bike_id        INTEGER NOT NULL REFERENCES bikes(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL,
    name           TEXT NOT NULL DEFAULT '',
    installed_at   TEXT NOT NULL,
    interval_km    REAL,
    interval_days  INTEGER,
    interval_hours REAL,
    active         INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS rides (
    id         TEXT PRIMARY KEY,
    bike_id    INTEGER REFERENCES bikes(id) ON DELETE SET NULL,
    start      TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    sport      TEXT NOT NULL DEFAULT 'Ride',
    distance_m REAL NOT NULL DEFAULT 0,
    moving_s   REAL NOT NULL DEFAULT 0,
    elev_m     REAL NOT NULL DEFAULT 0,
    trainer    INTEGER NOT NULL DEFAULT 0,
    commute    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS rides_bike_start ON rides(bike_id, start);
CREATE TABLE IF NOT EXISTS logs (
    id           INTEGER PRIMARY KEY,
    bike_id      INTEGER NOT NULL REFERENCES bikes(id) ON DELETE CASCADE,
    component_id INTEGER REFERENCES components(id) ON DELETE SET NULL,
    at           TEXT NOT NULL,
    action       TEXT NOT NULL DEFAULT 'service',
    note         TEXT NOT NULL DEFAULT '',
    cost         REAL
);
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DB:
    def __init__(self, path: str | Path = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    # -- plumbing ---------------------------------------------------------
    def q(self, sql: str, *args) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, args)]

    def one(self, sql: str, *args) -> dict | None:
        r = self.conn.execute(sql, args).fetchone()
        return dict(r) if r else None

    def run(self, sql: str, *args) -> int:
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur.lastrowid

    def get(self, key: str, default=None):
        r = self.one("SELECT value FROM kv WHERE key = ?", key)
        return json.loads(r["value"]) if r else default

    def put(self, key: str, value) -> None:
        self.run("INSERT INTO kv(key, value) VALUES(?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 key, json.dumps(value))

    def delete_key(self, key: str) -> None:
        self.run("DELETE FROM kv WHERE key = ?", key)

    # -- bikes ------------------------------------------------------------
    def add_bike(self, name: str, frame: str = "road", strava_gear_id=None,
                 installed_at: str | None = None, defaults: bool = True) -> int:
        bike_id = self.run(
            "INSERT INTO bikes(name, frame, strava_gear_id) VALUES(?, ?, ?)",
            name, frame, strava_gear_id)
        if defaults:
            for key in catalog.DEFAULT_SET.get(frame, catalog.DEFAULT_SET["road"]):
                self.add_component(bike_id, key, installed_at=installed_at)
        return bike_id

    def add_component(self, bike_id: int, kind: str, name: str = "",
                      installed_at: str | None = None, interval_km=None,
                      interval_days=None, interval_hours=None) -> int:
        return self.run(
            "INSERT INTO components(bike_id, kind, name, installed_at, "
            "interval_km, interval_days, interval_hours) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            bike_id, kind, name, installed_at or now(),
            interval_km, interval_days, interval_hours)

    def upsert_ride(self, r: dict) -> None:
        self.conn.execute(
            "INSERT INTO rides(id, bike_id, start, name, sport, distance_m, "
            "moving_s, elev_m, trainer, commute) "
            "VALUES(:id, :bike_id, :start, :name, :sport, :distance_m, "
            ":moving_s, :elev_m, :trainer, :commute) "
            "ON CONFLICT(id) DO UPDATE SET bike_id = excluded.bike_id, "
            "start = excluded.start, name = excluded.name, "
            "sport = excluded.sport, distance_m = excluded.distance_m, "
            "moving_s = excluded.moving_s, elev_m = excluded.elev_m, "
            "trainer = excluded.trainer, commute = excluded.commute", r)
        self.conn.commit()

    def log_service(self, component_id: int, at: str | None = None,
                    note: str = "", cost=None, action: str | None = None) -> int:
        c = self.one("SELECT * FROM components WHERE id = ?", component_id)
        if not c:
            raise KeyError(component_id)
        action = action or catalog.kind(c["kind"]).action
        return self.run(
            "INSERT INTO logs(bike_id, component_id, at, action, note, cost) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            c["bike_id"], component_id, at or now(), action, note, cost)
