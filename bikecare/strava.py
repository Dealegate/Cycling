"""Strava: OAuth, then a read-only pull of bikes and rides.

You need your own API application at https://www.strava.com/settings/api -
put its id and secret in STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET and set the
"Authorization Callback Domain" there to the host you open bikecare on
(``localhost`` for a laptop).  Nothing is ever written back to Strava.
"""
from __future__ import annotations

import calendar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import catalog
from .db import DB, now

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
DEAUTH_URL = "https://www.strava.com/oauth/deauthorize"
API = "https://www.strava.com/api/v3"
SCOPE = "read,profile:read_all,activity:read_all"
RESYNC_OVERLAP = 7 * 86400   # re-read the last week: gear gets changed late


class StravaError(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.environ.get("STRAVA_CLIENT_ID")
                and os.environ.get("STRAVA_CLIENT_SECRET"))


def authorize_url(redirect_uri: str, state: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "redirect_uri": redirect_uri, "response_type": "code",
        "approval_prompt": "auto", "scope": SCOPE, "state": state})


def _request(url: str, data: dict | None = None, token: str | None = None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise StravaError(f"Strava {e.code}: {detail}") from e


def _save_tokens(db: DB, t: dict) -> None:
    keep = db.get("strava", {})
    keep.update({k: t[k] for k in ("access_token", "refresh_token", "expires_at")})
    if t.get("athlete"):
        a = t["athlete"]
        keep["athlete"] = {"id": a.get("id"),
                           "name": f"{a.get('firstname', '')} {a.get('lastname', '')}".strip()}
    db.put("strava", keep)


def exchange_code(db: DB, code: str) -> None:
    _save_tokens(db, _request(TOKEN_URL, {
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "code": code, "grant_type": "authorization_code"}))


def access_token(db: DB) -> str:
    s = db.get("strava")
    if not s:
        raise StravaError("Strava не подключена")
    if s["expires_at"] < time.time() + 120:
        _save_tokens(db, _request(TOKEN_URL, {
            "client_id": os.environ["STRAVA_CLIENT_ID"],
            "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
            "refresh_token": s["refresh_token"],
            "grant_type": "refresh_token"}))
        s = db.get("strava")
    return s["access_token"]


def disconnect(db: DB) -> None:
    """Revoke the grant and drop the tokens.  Rides stay: they are what the
    maintenance history was computed from."""
    s = db.get("strava")
    if s:
        try:
            _request(DEAUTH_URL, {"access_token": s["access_token"]})
        except (StravaError, OSError):
            pass        # an expired token is as good as revoked
    db.delete_key("strava")


def ride_from_activity(a: dict, bike_id: int | None) -> dict:
    return {"id": f"strava:{a['id']}", "bike_id": bike_id,
            "start": a["start_date"], "name": a.get("name", ""),
            "sport": a.get("sport_type") or a.get("type") or "Ride",
            "distance_m": a.get("distance") or 0,
            "moving_s": a.get("moving_time") or 0,
            "elev_m": a.get("total_elevation_gain") or 0,
            "trainer": int(bool(a.get("trainer"))),
            "commute": int(bool(a.get("commute")))}


def wanted(a: dict) -> bool:
    """A cycling activity that actually went somewhere.  Watches log a
    zero-distance "indoor ride" next to the real one; it would only inflate
    the hours."""
    sport = a.get("sport_type") or a.get("type")
    return sport in catalog.CYCLING_SPORTS and (a.get("distance") or 0) > 0


def add_gear(db: DB, g: dict, installed_at: str | None = None) -> int:
    """A bike from a Strava gear record, unless it is already here."""
    gear_id = str(g["id"])
    row = db.one("SELECT id FROM bikes WHERE strava_gear_id = ?", gear_id)
    if row:
        return row["id"]
    frame = catalog.STRAVA_FRAME.get(g.get("frame_type"), "road")
    name = g.get("name") or " ".join(
        x for x in (g.get("brand_name"), g.get("model_name")) if x) or gear_id
    bike_id = db.add_bike(name, frame, strava_gear_id=gear_id,
                          installed_at=installed_at)
    if g.get("retired"):
        db.run("UPDATE bikes SET retired = 1 WHERE id = ?", bike_id)
    return bike_id


def _bike_for_gear(db: DB, gear_id: str, token: str, cache: dict) -> int:
    if gear_id not in cache:
        row = db.one("SELECT id FROM bikes WHERE strava_gear_id = ?", gear_id)
        cache[gear_id] = row["id"] if row else add_gear(
            db, _request(f"{API}/gear/{gear_id}", token=token))
    return cache[gear_id]


def import_dump(db: DB, dump: dict) -> dict:
    """Load ``{"bikes": [gear...], "activities": [activity...]}`` - the shapes
    GET /gear/{id} and GET /athlete/activities return - without OAuth.  For
    when the rides came out of Strava some other way.

    A bike's parts are taken to be as old as its first ride here: with the
    whole history in hand that is a better guess than "installed today".
    An hour before it, so that the first ride counts."""
    acts = [a for a in dump.get("activities", []) if wanted(a)]
    first: dict[str, str] = {}
    for a in acts:
        g = a.get("gear_id")
        if g and (str(g) not in first or a["start_date"] < first[str(g)]):
            first[str(g)] = a["start_date"]
    first = {g: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(calendar.timegm(
        time.strptime(t, "%Y-%m-%dT%H:%M:%SZ")) - 3600)) for g, t in first.items()}
    bikes = {str(g["id"]): add_gear(db, g, first.get(str(g["id"])))
             for g in dump.get("bikes", [])}
    for a in acts:
        g = a.get("gear_id")
        db.upsert_ride(ride_from_activity(a, bikes.get(str(g)) if g else None))
    return {"rides": len(acts), "bikes": len(bikes)}


def sync(db: DB) -> dict:
    """Pull the athlete's bikes and every cycling activity since the last
    sync.  Returns counts for the UI."""
    token = access_token(db)
    cache: dict[str, int] = {}
    athlete = _request(f"{API}/athlete", token=token)
    for b in athlete.get("bikes") or []:
        _bike_for_gear(db, b["id"], token, cache)

    state = db.get("strava")
    after = max(int(state.get("synced_until", 0)) - RESYNC_OVERLAP, 0)
    newest = after
    seen = page = 0
    while True:
        page += 1
        batch = _request(f"{API}/athlete/activities?" + urllib.parse.urlencode(
            {"after": after, "per_page": 200, "page": page}), token=token)
        if not batch:
            break
        for a in batch:
            if not wanted(a):
                continue
            gear = a.get("gear_id")
            bike_id = _bike_for_gear(db, gear, token, cache) if gear else None
            db.upsert_ride(ride_from_activity(a, bike_id))
            seen += 1
            newest = max(newest, calendar.timegm(
                time.strptime(a["start_date"], "%Y-%m-%dT%H:%M:%SZ")))
        if len(batch) < 200:
            break

    state = db.get("strava")
    state["synced_until"] = newest
    state["synced_at"] = now()
    db.put("strava", state)
    return {"rides": seen, "bikes": len(cache)}
