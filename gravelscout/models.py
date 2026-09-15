"""Core data structures shared by sources, filters and reporting."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Listing:
    """One classified ad, normalised across sources."""

    source: str
    source_id: str
    url: str
    title: str
    description: str = ""
    price_eur: float | None = None
    price_raw: str | None = None
    location: str | None = None
    posted_raw: str | None = None
    images: list[str] = field(default_factory=list)
    seller: str | None = None
    category: str | None = None
    first_seen: str = field(default_factory=_utcnow)
    last_seen: str = field(default_factory=_utcnow)
    detail_fetched: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        sid = self.source_id or hashlib.sha1(self.url.encode()).hexdigest()[:12]
        return f"{self.source}:{sid}"

    @property
    def text(self) -> str:
        """Everything a detector should read."""
        parts = [self.title, self.description, self.category or ""]
        for k in ("attributes", "specs"):
            v = self.raw.get(k)
            if isinstance(v, dict):
                parts += [f"{a} {b}" for a, b in v.items()]
            elif isinstance(v, (list, tuple)):
                parts += [str(x) for x in v]
        return "\n".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Listing":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Assessment:
    """The scout's opinion about one listing."""

    verdict: str                      # match | maybe | reject
    score: int                        # 0..100, only meaningful for match/maybe
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)   # work for a human/agent, not ad defects
    bike_type: str | None = None
    brand: str | None = None
    groupset: str | None = None
    groupset_tier: int = 0
    brakes: str | None = None
    bar: str | None = None
    size_label: str | None = None
    size_verdict: str | None = None
    rider_height_quoted: list[float] | None = None
    fit: dict | None = None           # geometry check, when the model is known
    model_guess: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
