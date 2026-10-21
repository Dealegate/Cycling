"""A made-up garage, so the app has something to show before Strava is
connected.  Seeded, so every run produces the same picture."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from .db import DB

FMT = "%Y-%m-%dT%H:%M:%SZ"


def seed(db: DB, today: datetime | None = None, days: int = 200) -> None:
    rnd = random.Random(42)
    today = today or datetime.now(timezone.utc)
    start = today - timedelta(days=days)
    iso = lambda d: d.strftime(FMT)

    gravel = db.add_bike("Rose Backroad", "gravel", installed_at=iso(start))
    road = db.add_bike("Giant Defy", "road", installed_at=iso(start))
    mtb = db.add_bike("Trek Fuel EX", "mtb", installed_at=iso(start))
    db.run("UPDATE bikes SET notes = ? WHERE id = ?",
           "GRX 1x11, 40T / 11-42. Покрышки 40 мм, tubeless.", gravel)

    n = 0
    for day in range(days):
        d = start + timedelta(days=day, hours=rnd.choice([7, 8, 17, 18]))
        weekend = d.weekday() >= 5
        roll = rnd.random()
        if weekend and roll < 0.7:
            bike, sport = rnd.choice([(gravel, "GravelRide"), (road, "Ride"),
                                      (mtb, "MountainBikeRide")])
            km = rnd.uniform(45, 110) if sport != "MountainBikeRide" else rnd.uniform(20, 40)
            elev = km * rnd.uniform(6, 22)
            speed = {"GravelRide": 22, "Ride": 27, "MountainBikeRide": 14}[sport]
            name, trainer, commute = "Выходная покатушка", 0, 0
        elif not weekend and roll < 0.45:
            bike, sport, km, elev, speed = gravel, "Ride", rnd.uniform(9, 14), 60, 20
            name, trainer, commute = "Дорога на работу", 0, 1
        elif not weekend and roll < 0.6 and (d.month in (11, 12, 1, 2, 3)):
            bike, sport, km, elev, speed = road, "VirtualRide", rnd.uniform(25, 40), 0, 30
            name, trainer, commute = "Zwift", 1, 0
        else:
            continue
        n += 1
        db.upsert_ride({"id": f"demo:{n}", "bike_id": bike, "start": iso(d),
                        "name": name, "sport": sport, "distance_m": km * 1000,
                        "moving_s": km / speed * 3600, "elev_m": elev,
                        "trainer": trainer, "commute": commute})

    # A few things already done, so the history tab is not empty.
    def comp(bike, kind):
        return db.one("SELECT id FROM components WHERE bike_id = ? AND kind = ?",
                      bike, kind)["id"]
    db.log_service(comp(gravel, "chain_lube"), iso(today - timedelta(days=9)),
                   "Squirt, после дождя")
    db.log_service(comp(gravel, "chain"), iso(today - timedelta(days=80)),
                   "KMC X11, старая растянута на 0.75", cost=35)
    db.log_service(comp(road, "chain_lube"), iso(today - timedelta(days=30)))
    db.log_service(comp(mtb, "chain_lube"), iso(today - timedelta(days=4)))
    db.log_service(comp(mtb, "fork_lowers"), iso(today - timedelta(days=60)))
    db.log_service(comp(mtb, "shock"), iso(today - timedelta(days=60)))
    db.log_service(comp(gravel, "sealant"), iso(today - timedelta(days=76)),
                   "Stan's, оба колеса")
    db.log_service(comp(gravel, "brake_pads_front"), iso(today - timedelta(days=50)),
                   "Shimano L05A", cost=18)
    db.log_service(comp(mtb, "sealant"), iso(today - timedelta(days=40)),
                   "Orange Seal, 90 мл на колесо")
    db.log_service(comp(road, "brake_pads_rear"), iso(today - timedelta(days=60)),
                   "Shimano L05A", cost=18)
