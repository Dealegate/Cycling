"""How worn each part is, and the one to-do list across every bike.

A component's counter starts at the later of its install date and its last
logged service.  Every ride on that bike after that moment adds its load (see
``ride_load``) to the effective kilometres, its moving time to the hours, and
the calendar keeps counting days regardless.  Whichever of the three is
furthest along its interval decides the status.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import catalog
from .db import DB

CLIMB_CAP = 4.0          # 40 m/km: past that the ride is a hill repeat anyway
SOON = 0.8               # share of the interval at which a part is "due soon"
CRITICAL = 1.2           # ... and at which "overdue" becomes "critical"
PACE_WINDOW = 42         # days of riding used to guess how soon "soon" is

ORDER = {"critical": 0, "overdue": 1, "soon": 2, "ok": 3, "idle": 4}


def parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ride_load(kind: catalog.Kind, ride: dict) -> float:
    """Effective kilometres this ride put on this kind of part."""
    km = (ride.get("distance_m") or 0) / 1000
    if ride.get("trainer") or ride.get("sport") == "VirtualRide":
        return km * kind.trainer
    mult = 1.0
    if ride.get("sport") in catalog.DIRT_SPORTS:
        mult += kind.dirt
    if km > 0:
        climb = min((ride.get("elev_m") or 0) / km / 10, CLIMB_CAP)
        mult += kind.climb * climb
    if ride.get("commute"):
        mult += 0.1           # stop-and-go, kerbs, whatever the weather was
    return km * mult


def intervals(c: dict) -> dict:
    k = catalog.kind(c["kind"])
    return {"km": c.get("interval_km") or k.km,
            "days": c.get("interval_days") or k.days,
            "hours": c.get("interval_hours") or k.hours}


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _amount(value: float, unit: str) -> str:
    v = round(value)
    if unit == "km":
        return f"{v} км"
    if unit == "days":
        return f"{v} {_plural(v, 'день', 'дня', 'дней')}"
    return f"{v} ч"


def component_status(c: dict, rides: list[dict], last_service: str | None,
                     at: datetime) -> dict:
    """Wear of one component.  ``rides`` are that bike's rides, any order."""
    k = catalog.kind(c["kind"])
    since = parse(c["installed_at"])
    if last_service and parse(last_service) > since:
        since = parse(last_service)

    used_km = used_h = 0.0
    used_rides = 0
    pace_km = pace_h = 0.0
    pace_rides = 0
    window = at - timedelta(days=PACE_WINDOW)
    for r in rides:
        start = parse(r["start"])
        load = ride_load(k, r)
        if window < start <= at:
            pace_km += load
            pace_h += r["moving_s"] / 3600
            pace_rides += 1
        if since < start <= at:
            used_km += load
            used_h += r["moving_s"] / 3600
            used_rides += 1
    used_days = max((at - since).total_seconds() / 86400, 0)

    lim = intervals(c)
    used = {"km": used_km, "days": used_days, "hours": used_h}
    shares = {u: used[u] / lim[u] for u in lim if lim[u]}
    out = {"since": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "used": {u: round(v, 1) for u, v in used.items()},
           "limits": lim, "rides": used_rides, "action": k.action,
           "prep": list(k.prep)}
    if not shares:
        return out | {"status": "idle", "progress": 0.0, "unit": None,
                      "label": "Без интервала", "eta_days": None}

    unit = max(shares, key=shares.get)
    progress = shares[unit]
    remaining = lim[unit] - used[unit]

    # How many days until each limit at the recent pace; the soonest wins.
    per_day = {"km": pace_km / PACE_WINDOW, "hours": pace_h / PACE_WINDOW,
               "days": 1.0}
    etas = {}
    for u in shares:
        left = lim[u] - used[u]
        if left <= 0:
            etas[u] = 0.0
        elif per_day[u] > 0:
            etas[u] = left / per_day[u]
    eta_days = min(etas.values()) if etas else None

    if progress >= 1:
        status = "critical" if progress >= CRITICAL else "overdue"
        label = f"Просрочено на {_amount(-remaining, unit)}"
    else:
        status = "soon" if progress >= SOON else "ok"
        load_per_ride = pace_km / pace_rides if pace_rides else 0
        if unit == "km" and load_per_ride > 0:
            n = max(1, round(remaining / load_per_ride))
            label = f"Через ~{n} {_plural(n, 'поездку', 'поездки', 'поездок')}"
        else:
            label = f"Осталось {_amount(remaining, unit)}"
    return out | {"status": status, "progress": round(progress, 3),
                  "unit": unit, "label": label,
                  "eta_days": None if eta_days is None else round(eta_days, 1)}


def fleet(db: DB, at: datetime | None = None, include_retired=False) -> list[dict]:
    """Every bike with its components' status, worst first within a bike."""
    at = at or datetime.now(timezone.utc)
    bikes = db.q("SELECT * FROM bikes" + ("" if include_retired
                                          else " WHERE retired = 0")
                 + " ORDER BY name")
    last = {r["component_id"]: r["at"] for r in db.q(
        "SELECT component_id, MAX(at) AS at FROM logs "
        "WHERE component_id IS NOT NULL AND action != 'note' "
        "GROUP BY component_id")}
    for b in bikes:
        rides = db.q("SELECT * FROM rides WHERE bike_id = ?", b["id"])
        b["total_km"] = round(sum(r["distance_m"] for r in rides) / 1000)
        b["ride_count"] = len(rides)
        comps = db.q("SELECT * FROM components WHERE bike_id = ? AND active = 1",
                     b["id"])
        for c in comps:
            c["label_kind"] = catalog.kind(c["kind"]).label
            c["wear"] = component_status(c, rides, last.get(c["id"]), at)
        comps.sort(key=lambda c: (ORDER[c["wear"]["status"]],
                                  -c["wear"]["progress"]))
        b["components"] = comps
        b["worst"] = comps[0]["wear"]["status"] if comps else "idle"
    return bikes


def todo(db: DB, at: datetime | None = None, horizon: float = SOON) -> list[dict]:
    """The one list: everything at or past ``horizon`` of its interval, on
    every active bike, most urgent first."""
    items = []
    for b in fleet(db, at):
        for c in b["components"]:
            if c["wear"]["progress"] >= horizon:
                items.append({"bike_id": b["id"], "bike": b["name"],
                              "component_id": c["id"], "kind": c["kind"],
                              "title": c["name"] or c["label_kind"],
                              "kind_label": c["label_kind"], **c["wear"]})
    items.sort(key=lambda i: (ORDER[i["status"]], -i["progress"]))
    return items
