"""Offline tests for the maintenance tracker: no network, no Strava.

Run with ``python -m unittest discover tests`` or ``python tests/test_bikecare.py``.
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bikecare import catalog, demo, strava, wear
from bikecare.db import DB
from bikecare.server import App

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
FMT = "%Y-%m-%dT%H:%M:%SZ"


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime(FMT)


def ride(n, bike, days_ago, km=50, elev=0, sport="Ride", trainer=0, hours=2.0):
    return {"id": f"t:{n}", "bike_id": bike, "start": iso(days_ago), "name": "",
            "sport": sport, "distance_m": km * 1000, "moving_s": hours * 3600,
            "elev_m": elev, "trainer": trainer, "commute": 0}


def comp(db, bike, kind):
    return db.one("SELECT id FROM components WHERE bike_id = ? AND kind = ?",
                  bike, kind)["id"]


class RideLoad(unittest.TestCase):
    def test_trainer_spares_the_brakes_but_not_the_chain(self):
        r = ride(1, 1, 0, km=40, trainer=1)
        self.assertEqual(wear.ride_load(catalog.kind("brake_pads_front"), r), 0)
        self.assertEqual(wear.ride_load(catalog.kind("chain"), r), 40)

    def test_dirt_and_climbing_count_extra(self):
        pads = catalog.kind("brake_pads_front")
        flat = wear.ride_load(pads, ride(1, 1, 0, km=50))
        gravel = wear.ride_load(pads, ride(1, 1, 0, km=50, sport="GravelRide"))
        hilly = wear.ride_load(pads, ride(1, 1, 0, km=50, elev=1000))
        self.assertEqual(flat, 50)
        self.assertGreater(gravel, flat)
        self.assertGreater(hilly, flat)

    def test_climbing_is_capped(self):
        pads = catalog.kind("brake_pads_front")
        steep = wear.ride_load(pads, ride(1, 1, 0, km=1, elev=500))
        self.assertAlmostEqual(steep, 1 * (1 + pads.climb * wear.CLIMB_CAP))


class Status(unittest.TestCase):
    def setUp(self):
        self.db = DB()
        self.addCleanup(self.db.conn.close)
        self.bike = self.db.add_bike("Test", "gravel", installed_at=iso(100))

    def chain(self):
        for b in wear.fleet(self.db, NOW):
            for c in b["components"]:
                if c["kind"] == "chain":
                    return c["wear"]

    def test_fresh_bike_is_ok(self):
        self.db.upsert_ride(ride(1, self.bike, 5, km=100))
        w = self.chain()
        self.assertEqual(w["status"], "ok")
        self.assertEqual(w["used"]["km"], 100)

    def test_overdue_then_critical(self):
        for i in range(31):                     # 3100 km of a 3000 km chain
            self.db.upsert_ride(ride(i, self.bike, 90 - i, km=100))
        self.assertEqual(self.chain()["status"], "overdue")
        self.assertIn("100 км", self.chain()["label"])
        for i in range(31, 40):
            self.db.upsert_ride(ride(i, self.bike, 90 - i, km=100))
        self.assertEqual(self.chain()["status"], "critical")

    def test_service_log_resets_the_counter(self):
        for i in range(35):
            self.db.upsert_ride(ride(i, self.bike, 90 - i, km=100))
        self.db.log_service(comp(self.db, self.bike, "chain"), iso(10))
        self.db.upsert_ride(ride(99, self.bike, 2, km=60))
        w = self.chain()
        self.assertEqual(w["used"]["km"], 60)
        self.assertEqual(w["status"], "ok")
        self.assertEqual(self.db.one("SELECT action FROM logs")["action"], "replace")

    def test_days_interval_runs_without_riding(self):
        self.db.log_service(comp(self.db, self.bike, "sealant"), iso(95))
        items = {i["kind"]: i for i in wear.todo(self.db, NOW)}
        self.assertEqual(items["sealant"]["status"], "overdue")
        self.assertEqual(items["sealant"]["unit"], "days")

    def test_rides_left_estimate(self):
        for i in range(27):                     # 2700 / 3000 km, 100 km a ride
            self.db.upsert_ride(ride(i, self.bike, 30 - i, km=100))
        w = self.chain()
        self.assertEqual(w["status"], "soon")
        self.assertEqual(w["label"], "Через ~3 поездки")

    def test_todo_is_sorted_and_skips_retired_bikes(self):
        other = self.db.add_bike("Old", "road", installed_at=iso(400))
        self.db.run("UPDATE bikes SET retired = 1 WHERE id = ?", other)
        items = wear.todo(self.db, NOW)
        self.assertTrue(all(i["bike_id"] == self.bike for i in items))
        ranks = [wear.ORDER[i["status"]] for i in items]
        self.assertEqual(ranks, sorted(ranks))

    def test_plural(self):
        self.assertEqual(wear._amount(1, "days"), "1 день")
        self.assertEqual(wear._amount(3, "days"), "3 дня")
        self.assertEqual(wear._amount(11, "days"), "11 дней")
        self.assertEqual(wear._amount(21, "days"), "21 день")


class Strava(unittest.TestCase):
    def test_sync_maps_gear_and_skips_runs(self):
        db = DB()
        self.addCleanup(db.conn.close)
        db.put("strava", {"access_token": "x", "refresh_token": "y",
                          "expires_at": 4_000_000_000})
        acts = [
            {"id": 1, "sport_type": "GravelRide", "gear_id": "b9", "distance": 42000,
             "moving_time": 7200, "total_elevation_gain": 300,
             "start_date": "2026-09-01T07:00:00Z", "name": "Gravel"},
            {"id": 2, "sport_type": "Run", "gear_id": "g1", "distance": 10000,
             "moving_time": 3000, "start_date": "2026-09-02T07:00:00Z"},
            {"id": 3, "sport_type": "VirtualRide", "gear_id": None, "trainer": True,
             "distance": 30000, "moving_time": 3600,
             "start_date": "2026-09-03T07:00:00Z"},
        ]

        def fake(url, data=None, token=None):
            if url.endswith("/athlete"):
                return {"bikes": [{"id": "b9", "name": "Backroad"}]}
            if "/gear/" in url:
                return {"id": "b9", "name": "Backroad", "frame_type": 5}
            if "page=1" in url:
                return acts
            return []

        with mock.patch.object(strava, "_request", side_effect=fake):
            out = strava.sync(db)
        self.assertEqual(out["rides"], 2)
        bike = db.one("SELECT * FROM bikes")
        self.assertEqual((bike["name"], bike["frame"]), ("Backroad", "gravel"))
        rides = {r["id"]: r for r in db.q("SELECT * FROM rides")}
        self.assertEqual(rides["strava:1"]["bike_id"], bike["id"])
        self.assertIsNone(rides["strava:3"]["bike_id"])
        self.assertEqual(rides["strava:3"]["trainer"], 1)
        self.assertEqual(db.get("strava")["synced_until"], 1788418800)


class Server(unittest.TestCase):
    def setUp(self):
        self.db = DB()
        demo.seed(self.db, NOW)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), App(self.db).handler())
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.db.conn.close()

    def call(self, path, body=None, method=None):
        req = urllib.request.Request(
            self.base + path, method=method or ("POST" if body is not None else "GET"),
            data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req) as r:
            return json.load(r) if "json" in r.headers["Content-Type"] else r.read()

    def test_state_and_round_trip(self):
        s = self.call("/api/state")
        self.assertEqual(len(s["bikes"]), 3)
        self.assertFalse(s["strava"]["connected"])
        b = self.call("/api/bikes", {"name": "Новый", "frame": "city"})
        cid = comp(self.db, b["id"], "chain")
        self.call(f"/api/components/{cid}/log", {"note": "KMC"})
        self.call(f"/api/components/{cid}", {"interval_km": "2500"})
        self.assertEqual(self.db.one("SELECT interval_km FROM components WHERE id = ?",
                                     cid)["interval_km"], 2500)
        self.call("/api/rides/demo%3A1", {"bike_id": b["id"]})
        self.assertEqual(self.db.one("SELECT bike_id FROM rides WHERE id = 'demo:1'")
                         ["bike_id"], b["id"])
        self.assertIn(b"bikecare", self.call("/"))

    def test_static_cannot_escape(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call("/../db.py")
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
