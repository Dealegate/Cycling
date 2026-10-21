"""Command line entry point.

    python -m bikecare serve [--port 8765] [--host 127.0.0.1]
    python -m bikecare demo               fill an empty database with a made-up garage
    python -m bikecare sync               pull new rides from Strava once
    python -m bikecare import dump.json   load bikes and rides from a JSON file
    python -m bikecare todo               print the to-do list
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import demo, strava, wear
from .db import DB

DEFAULT_DB = os.environ.get("BIKECARE_DB", "data/bikecare.sqlite")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="bikecare")
    p.add_argument("--db", default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    sub.add_parser("demo")
    sub.add_parser("sync")
    i = sub.add_parser("import")
    i.add_argument("file")
    sub.add_parser("todo")
    args = p.parse_args(argv)
    db = DB(args.db)

    if args.cmd == "serve":
        from .server import serve
        serve(db, args.host, args.port)
    elif args.cmd == "demo":
        if db.one("SELECT 1 FROM bikes LIMIT 1"):
            print("В базе уже есть велосипеды; демо кладётся только в пустую.",
                  file=sys.stderr)
            return 1
        demo.seed(db)
        print(f"Демо-гараж записан в {args.db}")
    elif args.cmd == "sync":
        print(strava.sync(db))
    elif args.cmd == "import":
        with open(args.file, encoding="utf-8") as f:
            print(strava.import_dump(db, json.load(f)))
    elif args.cmd == "todo":
        for i in wear.todo(db):
            print(f"{i['status']:9} {i['bike']:20} {i['title']:24} {i['label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
