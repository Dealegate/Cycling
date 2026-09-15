"""Frame-size extraction and the rider's size window.

Serbian ads write frame size as a bare number ("vel. 52"), a letter ("S"),
a combination ("M/54"), or not at all.  Wheel sizes (28", 27.5, 700c) live in
the same sentence, so every numeric candidate is checked against a plausible
frame-size range and against explicit wheel-size wording before it is accepted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import norm

# Letter size -> (min_cm, max_cm) for drop-bar gravel/road frames.  Brands
# disagree by a centimetre or two; the ranges below are deliberately generous
# because they are only used to decide whether a listing is worth a closer look.
LETTER_CM = {
    "xxs": (42, 46),
    "xs": (44, 49),
    "s": (49, 53),
    "m": (53, 56),
    "ml": (55, 57),
    "l": (56, 59),
    "xl": (59, 62),
    "xxl": (61, 65),
}

_SIZE_WORDS = r"\b(?:vel(?:icin[ae])?\.?|velicina|size|ram(?:a|e)?|okvir(?:a)?|visina\s*ram[ae]|frame(?:\s*size)?)"
_LETTER = r"(xxs|xs|s|m|ml|l|xl|xxl)"

# "28 inca" / "700c" / "27,5" are wheels, never frames.
_WHEEL_CTX = r"(?:inc\w*|\"|''|cola|700\s*c|650\s*b|tock\w*|felne?|gume?|\bbar\b|\bpsi\b)"


@dataclass
class Size:
    cm: float | None = None
    letter: str | None = None
    evidence: str | None = None

    @property
    def label(self) -> str:
        if self.cm and self.letter:
            return f"{self.letter.upper()}/{self.cm:g}"
        if self.cm:
            return f"{self.cm:g} cm"
        if self.letter:
            return self.letter.upper()
        return "?"

    @property
    def cm_range(self) -> tuple[float, float] | None:
        """Best available centimetre range, widened from the letter if needed."""
        if self.cm:
            return (self.cm, self.cm)
        if self.letter and self.letter in LETTER_CM:
            return LETTER_CM[self.letter]
        return None


def _numeric_candidates(t: str) -> list[tuple[float, str, int]]:
    """(value, evidence, score) for every number that could be a frame size."""
    out: list[tuple[float, str, int]] = []
    # Strongest: an explicit size word next to the number.
    for m in re.finditer(_SIZE_WORDS + r"\s*[:\-]?\s*(\d{2}(?:[.,]\d)?)\s*(cm)?", t):
        out.append((float(m.group(1).replace(",", ".")), m.group(0), 3))
    # Number followed by cm, but not if it is talking about wheels.
    for m in re.finditer(r"\b(\d{2}(?:[.,]\d)?)\s*cm\b", t):
        val = float(m.group(1).replace(",", "."))
        tail = t[max(0, m.start() - 24): m.start()]
        if re.search(r"tock|feln|gum|inc", tail):
            continue
        out.append((val, m.group(0), 2))
    # Bare two-digit number in the plausible frame range.
    for m in re.finditer(r"\b(4[2-9]|5[0-9]|6[0-4])\b", t):
        around = t[max(0, m.start() - 14): m.end() + 14]
        if re.search(_WHEEL_CTX, around) or re.search(r"\b(19|20)\d\d\b", around):
            continue
        out.append((float(m.group(1)), m.group(0), 1))
    return out


def parse_size(text: str) -> Size:
    t = norm(text)
    size = Size()

    # Letter size, e.g. "vel. S", "size M", "S/M", "(S)".
    lm = (re.search(_SIZE_WORDS + r"\s*[:\-]?\s*" + _LETTER + r"\b", t)
          or re.search(r"\b" + _LETTER + r"\s*(?:/|\s)\s*(\d{2})\s*(?:cm)?\b", t)
          or re.search(r"\((" + _LETTER[1:-1] + r")\)", t))
    if lm:
        letter = next((g for g in lm.groups() if g and g.lower() in LETTER_CM), None)
        if letter:
            size.letter = letter.lower()
            size.evidence = lm.group(0)

    # "S/52", "M 54" - letter and centimetres given together.
    combo = re.search(r"\b" + _LETTER + r"\s*[/\- ]\s*(\d{2})(?:\s*cm)?\b", t)
    if combo and 40 <= float(combo.group(2)) <= 65:
        size.letter = size.letter or combo.group(1)
        size.cm = float(combo.group(2))
        size.evidence = combo.group(0)
        return size

    cands = _numeric_candidates(t)
    if cands:
        cands.sort(key=lambda c: (-c[2], abs(c[0] - 53)))
        val, ev, _score = cands[0]
        if 40 <= val <= 65:
            size.cm = val
            size.evidence = f"{size.evidence}; {ev}" if size.evidence else ev
    return size


@dataclass
class SizeWindow:
    """The frame sizes we are willing to look at."""

    cm_min: float = 47.0
    cm_max: float = 52.0
    letters: tuple[str, ...] = ("xxs", "xs", "s")

    def check(self, size: Size) -> tuple[str, str]:
        """Return ``(verdict, reason)`` where verdict is ok / out / unknown."""
        if size.cm is not None:
            if self.cm_min <= size.cm <= self.cm_max:
                return "ok", f"{size.cm:g} cm is inside {self.cm_min:g}-{self.cm_max:g}"
            return "out", f"{size.cm:g} cm is outside {self.cm_min:g}-{self.cm_max:g}"
        if size.letter:
            if size.letter in self.letters:
                return "ok", f"size {size.letter.upper()} is in {'/'.join(s.upper() for s in self.letters)}"
            return "out", f"size {size.letter.upper()} is outside {'/'.join(s.upper() for s in self.letters)}"
        return "unknown", "no frame size in the ad"


# --------------------------------------------------------------------------
# Rider fit targets derived from body measurements
# --------------------------------------------------------------------------
SADDLE_HEIGHT_FACTOR = 0.883  # LeMond: saddle height = inseam * 0.883 (BB to saddle top)


def saddle_height_range(inseam_cm_min: float, inseam_cm_max: float) -> tuple[float, float]:
    return (round(inseam_cm_min * SADDLE_HEIGHT_FACTOR * 10, 1),
            round(inseam_cm_max * SADDLE_HEIGHT_FACTOR * 10, 1))


def max_standover_mm(inseam_cm_min: float, clearance_mm: float = 20.0) -> float:
    """Barefoot inseam minus a gravel-appropriate clearance, in millimetres."""
    return inseam_cm_min * 10 - clearance_mm
