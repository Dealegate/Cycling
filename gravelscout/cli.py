"""Command line entry point.

    python -m gravelscout run            crawl every enabled source once
    python -m gravelscout run --watch    keep crawling on an interval
    python -m gravelscout probe          fetch one page per source and report
                                         which parsing strategy worked
    python -m gravelscout check "text"   run the filters over pasted ad text
    python -m gravelscout inspect <url>  fetch one ad and show what was parsed
    python -m gravelscout telegram       test the bot, print the chat id
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import Config
from .geometry import GeometryDB
from .models import Listing
from .notify import (github_enabled, github_issue, issue_body, telegram_diagnose,
                     telegram_enabled, telegram_send)
from .report import console_line, markdown, summary_counts
from .scoring import assess
from .sources import build_sources
from .sources.base import HttpClient
from .state import Store


def _http(cfg: Config, dump: bool = False) -> HttpClient:
    h = cfg.get("http", {})
    return HttpClient(user_agent=" ".join(h.get("user_agent", "gravelscout/1.0").split()),
                      delay_seconds=float(h.get("delay_seconds", 2.0)),
                      timeout=float(h.get("timeout_seconds", 25)),
                      retries=int(h.get("retries", 3)), dump=dump)


def cmd_run(args) -> int:
    cfg = Config.load(args.config)
    db = GeometryDB(args.geometry) if args.geometry else GeometryDB()
    window = cfg.fit_window(db)
    out_cfg = cfg.get("output", {})
    store = Store.load(args.state or out_cfg.get("state_file", "data/seen.json"))
    drop_pct = float(out_cfg.get("price_drop_alert_pct", 7))

    http = _http(cfg, dump=args.dump)
    sources = build_sources(cfg, http)
    if not sources:
        print("No sources enabled in the config.")
        return 1

    print(f"Fit window: {window.describe()}")
    print(f"Anchor bike: {db.anchor.label} (stack {db.anchor.stack}, reach {db.anchor.reach})")
    print(f"Crawling {len(sources)} source(s)...")

    listings: list[Listing] = []
    for s in sources:
        try:
            listings += s.crawl()
        except Exception as exc:  # noqa: BLE001 - one broken site must not stop the rest
            print(f"  ! {s.name} failed: {type(exc).__name__}: {exc}")
    print(f"Collected {len(listings)} listing(s).")
    for host, why in sorted(http.blocked.items()):
        print(f"  ! nothing from {host}: {why}")

    by_source = {s.name: s for s in sources}
    results = []
    for l in listings:
        a = assess(l, cfg, db, window)
        if a.verdict == "reject":
            store.record(l, a, price_drop_pct=drop_pct)
            continue
        # Only spend a detail request on listings that already look plausible.
        if not l.detail_fetched and not args.no_detail:
            src = by_source.get(l.source)
            if src:
                try:
                    src.fetch_detail(l)
                    a = assess(l, cfg, db, window)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! detail fetch failed for {l.url}: {exc}")
        if a.verdict == "reject":
            store.record(l, a, price_drop_pct=drop_pct)
            continue
        status = store.record(l, a, price_drop_pct=drop_pct)
        results.append((l, a, status))

    results.sort(key=lambda r: (-r[1].score, r[0].title))
    fresh = [r for r in results if r[2] in ("new", "price-drop", "upgraded")]
    to_show = results if args.all else fresh

    print()
    print(f"{len(results)} candidate(s) pass the filters, {len(fresh)} of them new this run.")
    print()
    for l, a, status in to_show:
        print(console_line(l, a, status))
        print()

    report_dir = Path(args.report_dir or out_cfg.get("report_dir", "out"))
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "shortlist.md").write_text(
        markdown(results, window_desc=window.describe()), encoding="utf-8")
    (report_dir / "new.md").write_text(
        markdown(fresh, window_desc=window.describe(), title="New this run"), encoding="utf-8")
    print(f"Reports written to {report_dir}/shortlist.md and {report_dir}/new.md")

    if not args.no_notify:
        for l, a, status in fresh:
            if telegram_enabled():
                telegram_send(l, a, status)
            if github_enabled():
                github_issue(l, a, status, issue_body(l, a, status))

    store.prune()
    store.save()
    print("State:", summary_counts(results))
    return 0


def cmd_watch(args) -> int:
    interval = args.interval * 60
    while True:
        try:
            cmd_run(args)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001 - a watch loop should outlive one bad run
            print(f"! run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"\nSleeping {args.interval} min...\n")
        time.sleep(interval)


def cmd_probe(args) -> int:
    """Fetch the first page of each source and report what the parsers saw."""
    cfg = Config.load(args.config)
    http = _http(cfg, dump=True)
    ok = True
    for s in build_sources(cfg, http):
        name, url = next(iter(s.page_urls()))
        html = http.get(url, referer=s.base_url)
        if not html:
            print(f"{s.name:<20} {http.last_reason or 'NO RESPONSE'}  {url}")
            ok = False
            continue
        found = s.parse_page(html, url)
        strategies = {l.raw.get("strategy", "json") for l in found}
        print(f"{s.name:<20} {len(found):>3} listings via {','.join(sorted(strategies)) or '-'}  {url}")
        for l in found[:3]:
            print(f"    - {l.title[:60]!r} {l.price_eur} {l.url}")
        if not found:
            ok = False
            print(f"    (raw HTML saved under debug/ - the link pattern for {s.name} needs a look)")
    return 0 if ok else 2


def cmd_check(args) -> int:
    """Run the filters over pasted ad text, for tuning and spot checks."""
    cfg = Config.load(args.config)
    db = GeometryDB()
    text = args.text or sys.stdin.read()
    l = Listing(source="manual", source_id="0", url=args.url or "-",
                title=text.splitlines()[0][:120] if text else "", description=text)
    a = assess(l, cfg, db)
    print(f"verdict: {a.verdict}  score: {a.score}")
    print(f"type={a.bike_type} groupset={a.groupset} brakes={a.brakes} bar={a.bar} size={a.size_label}")
    for r in a.reasons:
        print("  +", r)
    for u in a.unknowns:
        print("  ?", u)
    for t in a.todos:
        print("  TODO", t)
    for b in a.blockers:
        print("  x", b)
    return 0


def cmd_inspect(args) -> int:
    """Fetch one ad and print everything the parsers made of it.

    For boards this machine cannot reach.  Whoever can reach them runs this on
    one URL and the output says exactly what was read and what was missed,
    which beats guessing at markup from the other side of a bot wall.
    """
    cfg = Config.load(args.config)
    db = GeometryDB(args.geometry) if args.geometry else GeometryDB()
    http = _http(cfg, dump=True)
    src = next((s for s in build_sources(cfg, http) if s.base_url in args.url), None)
    if src is None:
        print(f"No enabled source owns {args.url}")
        return 1

    # The title normally arrives from the listing page; inspect starts from a
    # bare URL, so seed it from the slug and let the detail page improve on it.
    slug = args.url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
    l = Listing(source=src.name, source_id="", url=args.url, title=slug)
    src.fetch_detail(l)
    if not l.detail_fetched:
        print(f"{src.name}: {http.last_reason or 'no response'}")
        return 2

    print(f"source      {src.name}")
    print(f"title       {l.title!r}")
    print(f"price       {l.price_eur} ({l.price_raw!r})")
    print(f"location    {l.location!r}")
    print(f"posted      {l.posted_raw!r}")
    print(f"images      {len(l.images)}")
    print(f"attributes  {l.raw.get('attributes') or {}}")
    desc = l.description or ""
    print(f"description {len(desc)} chars")
    print("  " + (desc[:600].replace("\n", "\n  ") if desc else "(empty)"))
    print()
    a = assess(l, cfg, db)
    print(f"verdict {a.verdict}  score {a.score}  brand={a.brand} type={a.bike_type} "
          f"size={a.size_label} groupset={a.groupset} brakes={a.brakes}")
    for r in a.reasons:
        print("  +", r)
    for u in a.unknowns:
        print("  ?", u)
    for b in a.blockers:
        print("  x", b)
    print(f"\nRaw HTML saved under debug/ - attach it if the fields above look wrong.")
    return 0


def cmd_telegram(args) -> int:
    """Verify the Telegram bot and print the chat id when it is still missing."""
    return telegram_diagnose()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gravelscout", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="crawl every enabled source once")
    run.add_argument("--state", help="path to the seen-listings file")
    run.add_argument("--geometry", help="path to an alternative geometry database")
    run.add_argument("--report-dir")
    run.add_argument("--all", action="store_true", help="print known candidates too, not just new ones")
    run.add_argument("--no-detail", action="store_true", help="skip per-ad detail requests")
    run.add_argument("--no-notify", action="store_true")
    run.add_argument("--dump", action="store_true", help="save raw HTML under debug/")
    run.add_argument("--watch", action="store_true", help="repeat forever")
    run.add_argument("--interval", type=int, default=20, help="minutes between runs in --watch")
    run.set_defaults(func=lambda a: cmd_watch(a) if a.watch else cmd_run(a))

    probe = sub.add_parser("probe", help="check that each source still parses")
    probe.set_defaults(func=cmd_probe)

    check = sub.add_parser("check", help="run the filters over pasted ad text")
    check.add_argument("text", nargs="?")
    check.add_argument("--url")
    check.set_defaults(func=cmd_check)

    insp = sub.add_parser("inspect", help="fetch one ad URL and show what was parsed")
    insp.add_argument("url")
    insp.add_argument("--geometry")
    insp.add_argument("--dump", action="store_true")
    insp.set_defaults(func=cmd_inspect)

    tg = sub.add_parser("telegram", help="test the Telegram bot and find the chat id")
    tg.set_defaults(func=cmd_telegram)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
