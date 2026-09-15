"""Text/price normalisation for Serbian classified ads.

Ads are written in a mix of Serbian Latin, Serbian Cyrillic, English and
transliterated slang, with prices in both EUR and RSD.  Everything that the
spec/size detectors see goes through :func:`norm` first, so the detectors only
ever have to match plain ASCII lowercase.
"""
from __future__ import annotations

import re
import unicodedata

# Serbian Cyrillic -> Latin (digraphs first).
_CYR_DIGRAPHS = {
    "Љ": "lj", "љ": "lj",
    "Њ": "nj", "њ": "nj",
    "Џ": "dz", "џ": "dz",
}
_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "ђ": "dj", "е": "e", "ж": "z", "з": "z", "и": "i",
    "ј": "j", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "ћ": "c", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "c", "џ": "dz", "ш": "s",
}

# Latin letters with diacritics -> ASCII.  "dj" for đ keeps words like
# "đubre"/"Đak" readable, and more importantly keeps brand names searchable.
_LAT = {"š": "s", "č": "c", "ć": "c", "ž": "z", "đ": "dj"}


def deaccent(text: str) -> str:
    out = []
    for ch in text:
        low = ch.lower()
        if low in _CYR_DIGRAPHS:
            out.append(_CYR_DIGRAPHS[low])
        elif low in _CYR:
            out.append(_CYR[low])
        elif low in _LAT:
            out.append(_LAT[low])
        else:
            out.append(low)
    s = "".join(out)
    # Strip any remaining combining marks (e.g. NFD-encoded input).
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def norm(text: str | None) -> str:
    """Lowercase, transliterate, collapse whitespace and unify separators."""
    if not text:
        return ""
    s = deaccent(text)
    s = s.replace(" ", " ").replace("–", "-").replace("—", "-")
    s = re.sub(r"[`'‘’“”]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def squeeze(text: str | None) -> str:
    """``norm`` plus removal of separators, so "R X 810" == "rx810".

    Used only for a second-chance match after the spaced patterns fail.
    """
    return re.sub(r"[\s._\-/]+", "", norm(text))


_PRICE_RE = re.compile(
    r"(?P<num>\d[\d.,\s ]*\d|\d)\s*(?P<cur>e(?:ur[ao]?|)\b|€|din(?:ara?)?\b|rsd\b|рсд\b)",
    re.IGNORECASE,
)
_CUR_BEFORE_RE = re.compile(
    r"(?P<cur>€|eur)\s*" + r"(?P<num>\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)",
    re.IGNORECASE)


def _to_number(raw: str) -> float | None:
    s = re.sub(r"[\s ]", "", raw)
    if not s:
        return None
    # Serbian convention: "." groups thousands, "," is the decimal comma.
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # A single comma with exactly two trailing digits is a decimal comma;
        # otherwise it is a thousands separator ("1,200").
        s = s.replace(",", "." if re.search(r",\d{1,2}$", s) else "")
    elif "." in s:
        s = s.replace(".", "") if re.search(r"\.\d{3}(\D|$)", s + " ") else s
    try:
        return float(s)
    except ValueError:
        return None


def parse_price(text: str | None, rsd_per_eur: float = 117.0) -> tuple[float | None, str | None]:
    """Return ``(price_in_eur, raw_match)`` for the first price found in *text*."""
    if not text:
        return None, None
    s = norm(text)
    m = _PRICE_RE.search(s) or _CUR_BEFORE_RE.search(s)
    if not m:
        # Bare number, e.g. a price field that already dropped its currency.
        m2 = re.search(r"\b(\d[\d.,\s]{2,})\b", s)
        if not m2:
            return None, None
        val = _to_number(m2.group(1))
        if val is None:
            return None, None
        # Heuristic: anything above 10k in a bare field is dinars.
        return (round(val / rsd_per_eur, 2) if val > 10000 else val), m2.group(1)
    val = _to_number(m.group("num"))
    if val is None:
        return None, None
    cur = m.group("cur").lower()
    if cur.startswith("din") or cur in ("rsd", "рсд"):
        return round(val / rsd_per_eur, 2), m.group(0)
    return val, m.group(0)
