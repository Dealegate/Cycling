"""Turn a raw listing into a verdict.

Three outcomes:

``reject``  the ad proves the bike is wrong (MTB, rim brakes, Sora, size 58)
``maybe``   nothing rules it out but something important is missing from the ad
``match``   every hard requirement is confirmed in the text

The distinction between "the ad says no" and "the ad does not say" matters:
Serbian sellers routinely omit the groupset and the frame size, and those ads
are exactly the ones worth a message rather than a silent drop.
"""
from __future__ import annotations

from .config import Config
from .geometry import GeometryDB, FitWindow, check_fit
from .models import Assessment, Listing
from .sizing import parse_size
from .specs import (
    detect_bar, detect_brakes, detect_groupset, detect_material,
    detect_type_with_model, detect_women,
)

# Groupsets that come with STI/DoubleTap levers: seeing one is good evidence of
# a drop bar even when the ad never mentions the handlebar.
DROPBAR_FAMILIES = {
    "grx", "tiagra", "105", "ultegra", "dura-ace", "dura ace", "duraace",
    "red", "force", "rival", "apex", "ekar", "chorus", "record", "super record",
    "potenza", "centaur", "athena", "veloce", "sensah", "centos", "sword", "empire",
}


def assess(listing: Listing, cfg: Config, db: GeometryDB,
           window: FitWindow | None = None) -> Assessment:
    text = listing.text
    req = cfg.get("requirements", {})
    window = window or cfg.fit_window(db)

    a = Assessment(verdict="maybe", score=0)
    reasons, blockers, unknowns, todos = a.reasons, a.blockers, a.unknowns, a.todos

    # -- type -------------------------------------------------------------
    t = detect_type_with_model(text)
    a.bike_type = t.value
    if t.value in req.get("reject_types", []):
        blockers.append(f"listed as {t.value} ({t.evidence})")
    elif t.value in req.get("bike_types", []):
        reasons.append(f"{t.value} ({t.evidence})")
    elif t.value == "road":
        unknowns.append(f"listed as a road bike ({t.evidence}) - could still be gravel-capable")
    elif t.value is None:
        unknowns.append("the ad never says what kind of bike this is")

    # -- groupset ---------------------------------------------------------
    gs = detect_groupset(text)
    a.groupset, a.groupset_tier = (gs.label if gs.family else None), gs.tier
    min_tier = req.get("min_groupset_tier", 3)
    if gs.family:
        if gs.tier >= min_tier:
            reasons.append(f"drivetrain {gs.label}")
        else:
            blockers.append(f"drivetrain {gs.label} is below the {min_tier}-tier floor")
    else:
        unknowns.append("no drivetrain named in the ad")
    if gs.chainrings == 1 and not req.get("allow_1x", True):
        blockers.append("1x drivetrain")
    elif gs.chainrings == 1:
        unknowns.append("1x drivetrain - check the low gear before the Belgrade hills")

    # -- brakes -----------------------------------------------------------
    br = detect_brakes(text)
    a.brakes = br.value
    if br.value == "hydraulic_disc":
        reasons.append(f"hydraulic discs ({br.evidence})")
    elif br.value in ("rim", "mechanical_disc"):
        blockers.append(f"{br.value.replace('_', ' ')} brakes ({br.evidence})")
    elif br.value == "disc_unknown_actuation":
        unknowns.append("disc brakes, but the ad does not say hydraulic or cable")
    else:
        unknowns.append("no brake type in the ad")

    # -- handlebar --------------------------------------------------------
    bar = detect_bar(text)
    if bar.value == "drop":
        a.bar = "drop"
        reasons.append(f"drop bar ({bar.evidence})")
    elif bar.value == "flat":
        a.bar = "flat"
        blockers.append(f"flat bar ({bar.evidence})")
    elif gs.family in DROPBAR_FAMILIES:
        a.bar = "drop (inferred)"
        reasons.append(f"drop bar inferred from the {gs.family.upper()} levers")
    else:
        unknowns.append("no handlebar type in the ad")

    # -- size -------------------------------------------------------------
    size = parse_size(text)
    a.size_label = size.label if (size.cm or size.letter) else None
    sv, sreason = cfg.size_window.check(size)
    a.size_verdict = sv
    if sv == "ok":
        reasons.append(sreason)
    elif sv == "out":
        blockers.append(sreason)
    else:
        unknowns.append(sreason)

    # -- geometry / fit ---------------------------------------------------
    ident = db.identify(text)
    if ident:
        brand, model = ident
        a.model_guess = f"{brand.title()} {model.title()}"
        rows = db.lookup(brand, model, size=size.letter, cm=size.cm)
        if rows:
            fits = [check_fit(g, window) for g in rows]
            best = min(fits, key=lambda f: {"fit": 0, "close": 1, "unknown": 2, "no-fit": 3}[f.verdict])
            a.fit = best.to_dict()
            if best.verdict == "fit":
                reasons.append(f"geometry matches the anchor bike ({best.geometry.label})")
            elif best.verdict == "close":
                unknowns.append(f"geometry is close but not identical ({best.geometry.label})")
            elif best.verdict == "no-fit":
                blockers.append(f"geometry does not fit ({best.geometry.label})")
        else:
            todos.append(f"{a.model_guess} is in the geometry database but size "
                         f"{size.label} is not - add that row")
    else:
        todos.append("identify the model and year from the photos, then check the "
                     "manufacturer's geometry chart")

    if detect_women(text):
        reasons.append("women's/Liv model")
    mat = detect_material(text)
    if mat:
        reasons.append(f"{mat.value} frame")

    # -- price ------------------------------------------------------------
    max_eur = cfg.get("price", {}).get("max_eur")
    if listing.price_eur and max_eur and listing.price_eur > max_eur:
        unknowns.append(f"asking EUR {listing.price_eur:.0f}, above the EUR {max_eur:.0f} guide price")

    # -- verdict ----------------------------------------------------------
    if blockers:
        a.verdict = "reject"
        a.score = 0
        return a

    a.score = _score(a, listing, gs)
    a.verdict = "match" if not unknowns else "maybe"
    if a.verdict == "match" and todos:
        reasons.append("hard requirements all confirmed; geometry still to be verified")
    return a


def _score(a: Assessment, listing: Listing, gs) -> int:
    """0-100, used only to sort the shortlist."""
    score = 40
    score += {5: 25, 4: 20, 3: 12, 2: 4, 1: 0, 0: 0}.get(a.groupset_tier, 0)
    if a.brakes == "hydraulic_disc":
        score += 12
    if a.bike_type in ("gravel", "cyclocross"):
        score += 8
    if a.size_verdict == "ok":
        score += 8
    if a.fit:
        score += {"fit": 12, "close": 6, "unknown": 0, "no-fit": -30}.get(a.fit["verdict"], 0)
    if gs.chainrings == 2:
        score += 5
    if listing.images:
        score += min(len(listing.images), 4)
    score -= 4 * len(a.unknowns)
    if listing.price_eur:
        if listing.price_eur <= 900:
            score += 6
        elif listing.price_eur >= 2000:
            score -= 4
    return max(0, min(100, score))
