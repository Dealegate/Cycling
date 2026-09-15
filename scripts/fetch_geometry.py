#!/usr/bin/env python3
"""Add a bike's geometry to data/geometry.yaml.

Two ways to use it:

    # look the numbers up yourself and type them in (always works)
    python scripts/fetch_geometry.py add --brand canyon --model grizl \
        --years 2021 2022 2023 --source https://www.canyon.com/... \
        --size XS stack=542 reach=371 seat_tube=445 standover=737 \
        --size S  stack=562 reach=376 seat_tube=473 standover=757

    # or try to scrape a geometry table off a page (needs internet)
    python scripts/fetch_geometry.py scrape --brand canyon --model grizl \
        --url https://geometrygeeks.bike/bike/canyon-grizl-al-2021/

The scraper is deliberately conservative: it only records rows whose header it
recognises, and marks everything it writes `confidence: medium` so the scout
still tells you to double-check against the manufacturer's own chart.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "geometry.yaml"

FIELD_ALIASES = {
    "stack": ("stack",),
    "reach": ("reach",),
    "top_tube": ("top tube", "effective top tube", "tt", "horizontal top tube", "ett"),
    "seat_tube": ("seat tube", "seat tube length", "st"),
    "standover": ("standover", "stand over", "standover height"),
    "head_tube": ("head tube", "head tube length", "ht"),
}


def load() -> dict:
    return yaml.safe_load(DB.read_text(encoding="utf-8")) or {}


def save(data: dict) -> None:
    DB.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
                  encoding="utf-8")


def upsert(data: dict, brand: str, model: str, years, source, confidence, sizes: dict) -> None:
    bikes = data.setdefault("bikes", [])
    for b in bikes:
        if b["brand"].lower() == brand.lower() and b["model"].lower() == model.lower():
            b.setdefault("sizes", {}).update(sizes)
            if years:
                b["years"] = sorted(set((b.get("years") or []) + list(years)))
            b["source"] = source or b.get("source")
            b["confidence"] = confidence
            return
    bikes.append({"brand": brand.lower(), "model": model.lower(),
                  "years": sorted(years) if years else None,
                  "source": source, "confidence": confidence, "sizes": sizes})


def parse_size_args(pairs: list[list[str]]) -> dict:
    sizes: dict[str, dict] = {}
    for group in pairs:
        if not group:
            continue
        name, *kvs = group
        row: dict[str, float] = {}
        for kv in kvs:
            if "=" not in kv:
                raise SystemExit(f"expected key=value, got {kv!r}")
            k, v = kv.split("=", 1)
            if k not in FIELD_ALIASES:
                raise SystemExit(f"unknown field {k!r}; known: {', '.join(FIELD_ALIASES)}")
            row[k] = float(v)
        sizes[name.upper()] = row
    return sizes


def cmd_add(args) -> int:
    data = load()
    upsert(data, args.brand, args.model, args.years, args.source,
           args.confidence, parse_size_args(args.size))
    save(data)
    print(f"wrote {len(args.size)} size row(s) for {args.brand} {args.model} to {DB}")
    return 0


def cmd_scrape(args) -> int:
    import requests
    from bs4 import BeautifulSoup

    from gravelscout.sources.base import PARSER

    r = requests.get(args.url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (compatible; gravelscout/1.0; geometry lookup)"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, PARSER)

    sizes: dict[str, dict] = {}
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        size_names = [h for h in header[1:] if h]
        if not size_names:
            continue
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) < 2:
                continue
            label = cells[0].lower().strip(" :")
            field = next((f for f, aliases in FIELD_ALIASES.items()
                          if any(label == a or label.startswith(a) for a in aliases)), None)
            if not field:
                continue
            for name, val in zip(size_names, cells[1:]):
                m = re.search(r"\d+(?:[.,]\d+)?", val)
                if not m:
                    continue
                num = float(m.group(0).replace(",", "."))
                if num < 100:      # the page is in centimetres
                    num *= 10
                sizes.setdefault(name.upper(), {})[field] = round(num)
    sizes = {k: v for k, v in sizes.items() if "stack" in v and "reach" in v}
    if not sizes:
        print(f"no recognisable geometry table at {args.url}", file=sys.stderr)
        print("Fall back to: fetch_geometry.py add --size S stack=... reach=...", file=sys.stderr)
        return 2

    data = load()
    upsert(data, args.brand, args.model, args.years, args.url, "medium", sizes)
    save(data)
    print(f"added {len(sizes)} size(s) for {args.brand} {args.model}: {', '.join(sorted(sizes))}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--brand", required=True)
    common.add_argument("--model", required=True)
    common.add_argument("--years", nargs="*", type=int)

    a = sub.add_parser("add", parents=[common], help="type the numbers in by hand")
    a.add_argument("--source", help="URL of the chart you copied from")
    a.add_argument("--confidence", choices=["high", "medium", "low"], default="high")
    a.add_argument("--size", nargs="+", action="append", required=True,
                   metavar="NAME k=v", help="e.g. --size S stack=558 reach=376")
    a.set_defaults(func=cmd_add)

    s = sub.add_parser("scrape", parents=[common], help="try to read a geometry table off a page")
    s.add_argument("--url", required=True)
    s.set_defaults(func=cmd_scrape)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
