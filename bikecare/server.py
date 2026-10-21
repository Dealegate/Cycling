"""A small JSON API plus the single-page UI, on the standard library alone.

GET  /api/state                      everything the UI draws from
POST /api/bikes                      {name, frame}
POST /api/bikes/<id>                 {name?, frame?, notes?, retired?}
DELETE /api/bikes/<id>
POST /api/bikes/<id>/components      {kind, name?, installed_at?, interval_*?}
POST /api/components/<id>            {name?, installed_at?, interval_*?, active?}
POST /api/components/<id>/log        {at?, note?, cost?, action?}
DELETE /api/logs/<id>
POST /api/rides                      manual ride {bike_id, start, distance_km, ...}
POST /api/rides/<id>                 {bike_id}   move a ride to another bike
POST /api/strava/sync | /api/strava/disconnect
GET  /strava/connect  ->  Strava  ->  /strava/callback
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import catalog, strava, wear
from .db import DB, now

STATIC = Path(__file__).parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
         ".css": "text/css", ".svg": "image/svg+xml"}
COMPONENT_FIELDS = ("name", "installed_at", "interval_km", "interval_days",
                    "interval_hours", "active")


def state(db: DB) -> dict:
    s = db.get("strava") or {}
    return {
        "bikes": wear.fleet(db, include_retired=True),
        "todo": wear.todo(db),
        "logs": db.q("SELECT l.*, b.name AS bike, c.kind, c.name AS component "
                     "FROM logs l JOIN bikes b ON b.id = l.bike_id "
                     "LEFT JOIN components c ON c.id = l.component_id "
                     "ORDER BY l.at DESC LIMIT 300"),
        "rides": db.q("SELECT r.*, b.name AS bike FROM rides r "
                      "LEFT JOIN bikes b ON b.id = r.bike_id "
                      "ORDER BY r.start DESC LIMIT 400"),
        "kinds": [{"key": k.key, "label": k.label, "km": k.km, "days": k.days,
                   "hours": k.hours, "action": k.action}
                  for k in catalog.KINDS.values()],
        "strava": {"configured": strava.configured(),
                   "connected": bool(s.get("access_token")),
                   "athlete": s.get("athlete"),
                   "synced_at": s.get("synced_at")},
    }


class App:
    def __init__(self, db: DB):
        self.db = db
        self.lock = threading.Lock()
        self.oauth_states: set[str] = set()

    # Routes: (method, regex) -> handler(match, body) -> json-able
    def routes(self):
        db = self.db
        num = lambda v: None if v in (None, "") else float(v)

        def add_bike(m, b):
            return {"id": db.add_bike(b["name"].strip() or "Велосипед",
                                      b.get("frame", "road"),
                                      installed_at=b.get("installed_at"))}

        def edit_bike(m, b):
            for f in ("name", "frame", "notes", "retired"):
                if f in b:
                    db.run(f"UPDATE bikes SET {f} = ? WHERE id = ?", b[f], int(m[1]))
            return {}

        def del_bike(m, b):
            db.run("DELETE FROM bikes WHERE id = ?", int(m[1]))
            return {}

        def add_comp(m, b):
            return {"id": db.add_component(
                int(m[1]), b["kind"], b.get("name", ""), b.get("installed_at"),
                num(b.get("interval_km")), num(b.get("interval_days")),
                num(b.get("interval_hours")))}

        def edit_comp(m, b):
            for f in COMPONENT_FIELDS:
                if f in b:
                    v = num(b[f]) if f.startswith("interval_") else b[f]
                    db.run(f"UPDATE components SET {f} = ? WHERE id = ?", v, int(m[1]))
            return {}

        def log(m, b):
            return {"id": db.log_service(int(m[1]), b.get("at") or None,
                                         b.get("note", ""), num(b.get("cost")),
                                         b.get("action"))}

        def del_log(m, b):
            db.run("DELETE FROM logs WHERE id = ?", int(m[1]))
            return {}

        def add_ride(m, b):
            km = float(b["distance_km"])
            db.upsert_ride({
                "id": f"manual:{uuid.uuid4().hex[:12]}",
                "bike_id": int(b["bike_id"]), "start": b.get("start") or now(),
                "name": b.get("name") or "Поездка", "sport": b.get("sport", "Ride"),
                "distance_m": km * 1000,
                "moving_s": float(b.get("hours") or km / 22) * 3600,
                "elev_m": float(b.get("elev_m") or 0),
                "trainer": int(bool(b.get("trainer"))),
                "commute": int(bool(b.get("commute")))})
            return {}

        def move_ride(m, b):
            db.run("UPDATE rides SET bike_id = ? WHERE id = ?",
                   b.get("bike_id"), m[1])
            return {}

        return [
            ("POST", r"/api/bikes", add_bike),
            ("POST", r"/api/bikes/(\d+)", edit_bike),
            ("DELETE", r"/api/bikes/(\d+)", del_bike),
            ("POST", r"/api/bikes/(\d+)/components", add_comp),
            ("POST", r"/api/components/(\d+)", edit_comp),
            ("POST", r"/api/components/(\d+)/log", log),
            ("DELETE", r"/api/logs/(\d+)", del_log),
            ("POST", r"/api/rides", add_ride),
            ("POST", r"/api/rides/([\w:]+)", move_ride),
            ("POST", r"/api/strava/sync", lambda m, b: strava.sync(db)),
            ("POST", r"/api/strava/disconnect",
             lambda m, b: strava.disconnect(db) or {}),
        ]

    def handler(self):
        app = self
        table = [(meth, re.compile(pat + "$"), fn) for meth, pat, fn in self.routes()]

        class H(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def _send(self, code, body: bytes, ctype="application/json",
                      headers=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code, obj):
                self._send(code, json.dumps(obj, ensure_ascii=False).encode())

            def _redirect(self, where):
                self._send(302, b"", "text/plain", {"Location": where})

            def _base(self):
                return f"http://{self.headers.get('Host', 'localhost')}"

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/api/state":
                    with app.lock:
                        return self._json(200, state(app.db))
                if url.path == "/strava/connect":
                    if not strava.configured():
                        return self._redirect("/#strava-missing")
                    st = secrets.token_urlsafe(16)
                    app.oauth_states.add(st)
                    return self._redirect(strava.authorize_url(
                        self._base() + "/strava/callback", st))
                if url.path == "/strava/callback":
                    qs = parse_qs(url.query)
                    st = qs.get("state", [""])[0]
                    if st not in app.oauth_states or "code" not in qs:
                        return self._redirect("/#strava-denied")
                    app.oauth_states.discard(st)
                    try:
                        with app.lock:
                            strava.exchange_code(app.db, qs["code"][0])
                            strava.sync(app.db)
                    except Exception as e:
                        traceback.print_exc()
                        return self._redirect("/#strava-error")
                    return self._redirect("/#synced")
                name = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
                f = (STATIC / name).resolve()
                if STATIC.resolve() not in f.parents or not f.is_file():
                    return self._send(404, b"not found", "text/plain")
                self._send(200, f.read_bytes(),
                           TYPES.get(f.suffix, "application/octet-stream"))

            def _api(self, method):
                path = unquote(urlparse(self.path).path)
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except json.JSONDecodeError:
                    return self._json(400, {"error": "bad json"})
                for meth, pat, fn in table:
                    m = pat.match(path)
                    if m and meth == method:
                        try:
                            with app.lock:
                                return self._json(200, fn(m, body) or {})
                        except strava.StravaError as e:
                            return self._json(502, {"error": str(e)})
                        except (KeyError, ValueError, TypeError) as e:
                            return self._json(400, {"error": f"{type(e).__name__}: {e}"})
                self._json(404, {"error": "no such route"})

            def do_POST(self):
                self._api("POST")

            def do_DELETE(self):
                self._api("DELETE")

        return H


def serve(db: DB, host: str = "127.0.0.1", port: int = 8765) -> None:
    httpd = ThreadingHTTPServer((host, port), App(db).handler())
    print(f"bikecare: http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
