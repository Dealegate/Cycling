"""Frame geometry lookup and the fit verdict.

The fit window is anchored on a bike that already fit the rider rather than on
generic "your height means size 52" tables: we know a Liv Devote size S works,
so anything whose stack and reach land near the Devote S numbers should work
too.  Tolerances are wide enough to allow for a stem swap and spacers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .normalize import norm

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "geometry.yaml"


@dataclass
class Geometry:
    brand: str
    model: str
    size: str
    stack: float | None = None
    reach: float | None = None
    top_tube: float | None = None
    seat_tube: float | None = None
    standover: float | None = None
    head_tube: float | None = None
    years: list[int] | None = None
    source: str | None = None
    confidence: str = "low"

    @property
    def label(self) -> str:
        return f"{self.brand.title()} {self.model.title()} [{self.size}]"


@dataclass
class FitWindow:
    """Acceptable geometry, expressed as ranges in millimetres."""

    stack_min: float
    stack_max: float
    reach_min: float
    reach_max: float
    standover_max: float | None = None
    seat_tube_max: float | None = None

    @classmethod
    def from_anchor(cls, anchor: Geometry, *, stack_tol: float = 28.0,
                    reach_tol: float = 18.0, standover_max: float | None = None,
                    seat_tube_max: float | None = None) -> "FitWindow":
        if anchor.stack is None or anchor.reach is None:
            raise ValueError("anchor bike needs both stack and reach")
        return cls(
            stack_min=anchor.stack - stack_tol, stack_max=anchor.stack + stack_tol,
            reach_min=anchor.reach - reach_tol, reach_max=anchor.reach + reach_tol,
            standover_max=standover_max, seat_tube_max=seat_tube_max,
        )

    def describe(self) -> str:
        s = (f"stack {self.stack_min:.0f}-{self.stack_max:.0f} mm, "
             f"reach {self.reach_min:.0f}-{self.reach_max:.0f} mm")
        if self.standover_max:
            s += f", standover <= {self.standover_max:.0f} mm"
        if self.seat_tube_max:
            s += f", seat tube <= {self.seat_tube_max:.0f} mm"
        return s


@dataclass
class FitResult:
    verdict: str            # fit | close | no-fit | unknown
    notes: list[str]
    geometry: Geometry | None = None

    def to_dict(self) -> dict:
        d = {"verdict": self.verdict, "notes": self.notes}
        if self.geometry:
            g = self.geometry
            d["geometry"] = {
                "label": g.label, "stack": g.stack, "reach": g.reach,
                "top_tube": g.top_tube, "seat_tube": g.seat_tube,
                "standover": g.standover, "source": g.source,
                "confidence": g.confidence,
            }
        return d


class GeometryDB:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self._anchor_raw = raw.get("anchor") or {}
        self.entries: list[Geometry] = []
        for bike in raw.get("bikes") or []:
            for size, g in (bike.get("sizes") or {}).items():
                self.entries.append(Geometry(
                    brand=bike["brand"], model=bike["model"], size=str(size),
                    years=bike.get("years"), source=bike.get("source"),
                    confidence=bike.get("confidence", "low"),
                    stack=g.get("stack"), reach=g.get("reach"),
                    top_tube=g.get("top_tube") or g.get("tt"),
                    seat_tube=g.get("seat_tube") or g.get("st"),
                    standover=g.get("standover"), head_tube=g.get("head_tube"),
                ))

    # -- lookup ------------------------------------------------------------
    @property
    def anchor(self) -> Geometry:
        a = self._anchor_raw
        return Geometry(brand=a.get("brand", "?"), model=a.get("model", "?"),
                        size=str(a.get("size", "?")), stack=a.get("stack"),
                        reach=a.get("reach"), source=a.get("source"),
                        confidence=a.get("confidence", "low"))

    def known_models(self) -> list[tuple[str, str]]:
        return sorted({(e.brand, e.model) for e in self.entries})

    def identify(self, text: str) -> tuple[str, str] | None:
        """Guess ``(brand, model)`` from ad text using the models we know."""
        t = norm(text)
        best = None
        for brand, model in self.known_models():
            mpat = r"\b" + re.escape(norm(model)).replace(r"\ ", r"\s*") + r"\b"
            if re.search(mpat, t):
                score = len(model) + (5 if re.search(r"\b" + re.escape(norm(brand)) + r"\b", t) else 0)
                if best is None or score > best[0]:
                    best = (score, (brand, model))
        return best[1] if best else None

    def lookup(self, brand: str, model: str, size: str | None = None,
               cm: float | None = None) -> list[Geometry]:
        rows = [e for e in self.entries
                if norm(e.brand) == norm(brand) and norm(e.model) == norm(model)]
        if size:
            want = norm(size)
            exact = [e for e in rows if norm(e.size) == want]
            if exact:
                return exact
        if cm is not None:
            with_cm = [(abs(_size_to_cm(e.size) - cm), e) for e in rows
                       if _size_to_cm(e.size) is not None]
            if with_cm:
                with_cm.sort(key=lambda p: p[0])
                return [e for d, e in with_cm if d <= 2.0] or [with_cm[0][1]]
        return rows


def _size_to_cm(size: str) -> float | None:
    m = re.search(r"\d{2}(?:[.,]\d)?", size or "")
    return float(m.group(0).replace(",", ".")) if m else None


def check_fit(geo: Geometry, window: FitWindow) -> FitResult:
    notes: list[str] = []
    hard_fail = False
    soft = 0

    if geo.stack is None or geo.reach is None:
        return FitResult("unknown", [f"{geo.label}: no stack/reach in the database"], geo)

    if window.stack_min <= geo.stack <= window.stack_max:
        notes.append(f"stack {geo.stack:.0f} mm is inside {window.stack_min:.0f}-{window.stack_max:.0f}")
    else:
        off = (geo.stack - window.stack_max) if geo.stack > window.stack_max else (geo.stack - window.stack_min)
        notes.append(f"stack {geo.stack:.0f} mm is {abs(off):.0f} mm "
                     f"{'too tall' if off > 0 else 'too low'}")
        if abs(off) > 20:
            hard_fail = True
        else:
            soft += 1

    if window.reach_min <= geo.reach <= window.reach_max:
        notes.append(f"reach {geo.reach:.0f} mm is inside {window.reach_min:.0f}-{window.reach_max:.0f}")
    else:
        off = (geo.reach - window.reach_max) if geo.reach > window.reach_max else (geo.reach - window.reach_min)
        notes.append(f"reach {geo.reach:.0f} mm is {abs(off):.0f} mm "
                     f"{'too long' if off > 0 else 'too short'} "
                     f"({'a shorter stem could cover it' if 0 < off <= 20 else 'a longer stem could cover it' if -20 <= off < 0 else 'beyond a stem swap'})")
        if abs(off) > 20:
            hard_fail = True
        else:
            soft += 1

    if window.standover_max and geo.standover:
        if geo.standover <= window.standover_max:
            notes.append(f"standover {geo.standover:.0f} mm clears the {window.standover_max:.0f} mm limit")
        else:
            notes.append(f"standover {geo.standover:.0f} mm exceeds the {window.standover_max:.0f} mm limit")
            hard_fail = True

    if window.seat_tube_max and geo.seat_tube:
        if geo.seat_tube > window.seat_tube_max:
            notes.append(f"seat tube {geo.seat_tube:.0f} mm is longer than {window.seat_tube_max:.0f} mm "
                         "- the saddle may not go low enough")
            soft += 1

    if geo.confidence == "low":
        notes.append("geometry row is marked low confidence - verify on the manufacturer's site")

    if hard_fail:
        return FitResult("no-fit", notes, geo)
    return FitResult("close" if soft else "fit", notes, geo)
