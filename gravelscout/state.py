"""Persistent memory of what has already been seen.

The state file is committed alongside the code so that a scheduled run on a
fresh machine still knows which ads are old.  It also keeps a price history, so
a bike that was passed over at EUR 1900 can be surfaced again when it drops.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .models import Assessment, Listing


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Store:
    path: Path
    data: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str) -> "Store":
        p = Path(path)
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                raw = {}
        else:
            raw = {}
        return cls(path=p, data=raw.get("listings", raw) if isinstance(raw, dict) else {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"updated": _utcnow(), "count": len(self.data), "listings": self.data}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
                             encoding="utf-8")

    # -- per-listing bookkeeping ------------------------------------------
    def record(self, listing: Listing, a: Assessment, *, price_drop_pct: float) -> str:
        """Update the store and classify the listing as new / price-drop / known."""
        key = listing.key
        prev = self.data.get(key)
        now = _utcnow()
        entry = {
            "url": listing.url,
            "title": listing.title,
            "source": listing.source,
            "price_eur": listing.price_eur,
            "verdict": a.verdict,
            "score": a.score,
            "first_seen": prev["first_seen"] if prev else now,
            "last_seen": now,
            "price_history": (prev or {}).get("price_history", []),
        }
        status = "known"
        if prev is None:
            status = "new"
            if listing.price_eur is not None:
                entry["price_history"] = [[now, listing.price_eur]]
        else:
            old_price = prev.get("price_eur")
            if (listing.price_eur is not None and old_price
                    and listing.price_eur < old_price * (1 - price_drop_pct / 100)):
                status = "price-drop"
                entry["price_history"] = prev.get("price_history", []) + [[now, listing.price_eur]]
                entry["previous_price_eur"] = old_price
            elif listing.price_eur is not None and old_price != listing.price_eur:
                entry["price_history"] = prev.get("price_history", []) + [[now, listing.price_eur]]
            # A listing that used to be rejected and now reads as a match
            # (the seller edited the ad) deserves a second look.
            if prev.get("verdict") in ("reject", None) and a.verdict in ("match", "maybe"):
                status = "upgraded"
        self.data[key] = entry
        return status

    def prune(self, keep_days: int = 180) -> int:
        """Drop entries not seen for a long time so the file stays readable."""
        cutoff = datetime.now(timezone.utc).timestamp() - keep_days * 86400
        dropped = []
        for key, entry in list(self.data.items()):
            try:
                ts = datetime.fromisoformat(entry["last_seen"]).timestamp()
            except (KeyError, ValueError):
                continue
            if ts < cutoff:
                dropped.append(key)
        for key in dropped:
            del self.data[key]
        return len(dropped)
