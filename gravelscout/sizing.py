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

# A letter standing on its own, as in "Gravel BOMBTRACK L sa GRX opremom".  Only
# trusted inside a title, and never for "s": that one is also the Serbian
# preposition "with", which turns up in half the titles on the board.  Reading a
# bare S wrongly would wave a wrong bike through; missing one only costs the ad
# a trip through the "size not stated" pile, which is the safe way to be wrong.
_BARE_LETTER = r"\b(xxs|xs|ml|xl|xxl|m|l)\b"


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


def parse_size(text: str, *, bare_letters: bool = False) -> Size:
    """Read a frame size out of *text*.

    ``bare_letters`` allows a letter with nothing to vouch for it, which is only
    safe for a title - a description mentions every size the seller has ever
    stocked.
    """
    t = norm(text)
    size = Size()

    # Letter size, e.g. "vel. S", "size M", "S/M", "(S)".
    lm = (re.search(_SIZE_WORDS + r"\s*[:\-]?\s*" + _LETTER + r"\b", t)
          # "M-SIZE", "L size", "XS ram" - the same thing written backwards,
          # and common enough in Serbian titles to matter for the size ceiling.
          or re.search(r"\b" + _LETTER + r"\s*[-\s]\s*" + _SIZE_WORDS[2:] + r"\b", t)
          or re.search(r"\b" + _LETTER + r"\s*(?:/|\s)\s*(\d{2})\s*(?:cm)?\b", t)
          or re.search(r"\((" + _LETTER[1:-1] + r")\)", t)
          or (re.search(_BARE_LETTER, t) if bare_letters else None))
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


# --------------------------------------------------------------------------
# The rider height a seller quotes
# --------------------------------------------------------------------------
# "XS 150-165cm", "Velicina SM 165-175cm", "za visinu 170 - 180 cm".  This is the
# one place an ad states fit in the rider's own units, and it beats a letter:
# an XS cut for 150-165 does not become a 168 cm bike because the letter is on
# the wanted list.  Only ranges in human-height territory count.
_HEIGHT_RANGE = re.compile(
    r"(?:visin\w*\s*(?:od\s*)?)?\b(1[4-9]\d|2[01]\d)\s*(?:cm)?\s*[-–—/]\s*"
    r"(1[4-9]\d|2[01]\d)\s*(?:cm|cm\w*)\b|"
    r"\bvisin\w*\s*(?:od\s*)?(1[4-9]\d|2[01]\d)\s*[-–—/]\s*(2[01]\d|1[4-9]\d)\b"
)


def rider_height_range(text: str) -> tuple[float, float] | None:
    """The rider height the ad says the bike is for, in centimetres."""
    m = _HEIGHT_RANGE.search(norm(text))
    if not m:
        return None
    lo, hi = [float(g) for g in m.groups() if g][:2]
    return (lo, hi) if lo < hi else (hi, lo)
