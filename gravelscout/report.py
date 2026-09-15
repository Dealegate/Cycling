"""Human-readable output: a terminal summary and a Markdown shortlist."""
from __future__ import annotations

from datetime import datetime, timezone

from .models import Assessment, Listing

STATUS_MARK = {"new": "NEW", "price-drop": "PRICE DROP", "upgraded": "RE-READ", "known": ""}


def price_str(l: Listing) -> str:
    if l.price_eur is None:
        return "price not stated"
    return f"EUR {l.price_eur:,.0f}".replace(",", " ")


def console_line(l: Listing, a: Assessment, status: str = "") -> str:
    mark = STATUS_MARK.get(status, "")
    head = f"[{a.score:>3}] {('* ' + mark) if mark else '  '} {l.title[:70]}"
    return (f"{head}\n"
            f"        {price_str(l)} | {l.location or 'location unknown'} | {l.source}\n"
            f"        {l.url}")


def markdown(results: list[tuple[Listing, Assessment, str]], *, window_desc: str,
             title: str = "Gravel scout") -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# {title}", "", f"_{now}_", "",
             f"Fit window: {window_desc}", ""]
    if not results:
        lines += ["Nothing new that clears the filters this run."]
        return "\n".join(lines)

    for l, a, status in results:
        mark = STATUS_MARK.get(status, "")
        badge = f"**{mark}** " if mark else ""
        lines.append(f"## {badge}{l.title}")
        lines.append("")
        lines.append(f"- **{price_str(l)}** - {l.location or 'location unknown'} - "
                     f"`{l.source}` - verdict **{a.verdict}** ({a.score}/100)")
        lines.append(f"- {l.url}")
        spec_bits = [b for b in (
            a.bike_type, a.groupset, a.brakes and a.brakes.replace("_", " "),
            a.bar, a.size_label and f"size {a.size_label}") if b]
        if spec_bits:
            lines.append(f"- Spec read from the ad: {', '.join(spec_bits)}")
        if a.fit:
            g = a.fit.get("geometry") or {}
            lines.append(f"- Fit: **{a.fit['verdict']}** - {g.get('label', '')} "
                         f"(stack {g.get('stack')}, reach {g.get('reach')})")
            for n in a.fit.get("notes", []):
                lines.append(f"  - {n}")
        for r in a.reasons:
            lines.append(f"  - + {r}")
        for u in a.unknowns:
            lines.append(f"  - ? {u}")
        for t in a.todos:
            lines.append(f"  - TODO {t}")
        if l.images:
            lines.append("")
            lines.append(" ".join(f"![photo]({u})" for u in l.images[:3]))
        lines.append("")
    return "\n".join(lines)


def summary_counts(results: list[tuple[Listing, Assessment, str]]) -> dict:
    out = {"match": 0, "maybe": 0, "new": 0, "price-drop": 0}
    for _l, a, status in results:
        out[a.verdict] = out.get(a.verdict, 0) + 1
        if status in out:
            out[status] += 1
    return out
