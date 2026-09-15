"""Detect bike type, groupset, brakes and handlebar from free-text ad copy.

Every detector returns both a value and the snippet it matched on, so a human
reviewing the shortlist can see *why* the scout believed something.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .normalize import norm, squeeze

# --------------------------------------------------------------------------
# Bike type
# --------------------------------------------------------------------------
# Order matters: the first family whose pattern hits wins, so gravel/cx are
# tested before the generic "drumski" road bucket that they are listed under.
TYPE_PATTERNS: list[tuple[str, str]] = [
    # All-road and endurance frames sit next to gravel on a shop floor and
    # nowhere near it on a gravel road: road clearances, road geometry, a tyre
    # that tops out around 35 mm.  Tested first so "allroad" is never read as
    # "gravel" on the strength of the second half of the word.
    ("allroad", r"\ball[\s-]?road\b|\bendurance\b|\bgran\s*fondo\b|\bgranfondo\b"),
    ("gravel", r"\bgravel\b|\bgravl\b|\bgrevel\b|\badventure\s+bike\b|\bsljunk"),
    ("cyclocross", r"\bciklo[\s-]?kros\b|\bcyclo[\s-]?cross\b|\bcyclocross\b|\bciklokros\b|\bcx\b"),
    ("ebike", r"\be-?bike\b|\belektri(c|cn)"),
    ("kids", r"\bdec(j|ij)i\b|\bdecak\b|\bdecji\b|\bza dete\b|\bdecije\b"),
    ("mtb", r"\bmtb\b|\bbrdski\b|\bplaninski\b|\bmountain\s*bike\b|\bhardtail\b|\bfull\s*suspension\b|\bdownhill\b|\benduro\b"),
    ("trekking", r"\btrek(k)?ing\b|\btreking\b|\bturing\b|\btouring\b|\bhibrid\b|\bhybrid\b|\bkrosover\b"),
    ("city", r"\bgradski\b|\bcity\s*bike\b|\bholandski\b|\bsklopiv\b|\bfolding\b"),
    ("road", r"\bdrumski\b|\btrkacki\b|\broad\s*bike\b|\bsoseni\b|\bcestni\b|\bracing\b|\baero\b|\btriatlon\b|\btt\b"),
]

# Model names that are unambiguously gravel, in case the ad text never says so.
GRAVEL_MODELS = r"""
 revolt|devote|grail|grizl|inflite|topstone|checkpoint|diverge|crux|domane\s*\+?gravel|
 warbird|cutthroat|midnight\s*special|fargo|vaya|straggler|crosscheck|crust|
 gt\s*grade|grade\s*carbon|jari|superx|caadx|arkose|
 addict\s*gravel|speedster\s*gravel|contessa\s*speedster\s*gravel|
 aspero|exploro|mr\.?\s*pink|nero|libre|mason|bombtrack|hook\s*ext|beyond|
 x-?night|kaius|
 x-?road|xroad|orbea\s*terra|terra\s*h30|terra\s*m30|
 cannondale\s*topstone|niner\s*rlt|rlt\s*9|salsa\s*journey|
 fuji\s*jari|marin\s*nicasio|marin\s*gestalt|gestalt|nicasio|
 kona\s*rove|rove\s*st|rove\s*nrb|lauf\s*seigla|seigla|
 ridley\s*kanzo|kanzo|
 ktm\s*x-?strada|x-?strada|scott\s*addict\s*gravel|
 bergamont\s*grandurance|grandurance|cube\s*nuroad|nuroad|
 focus\s*atlas|atlas\s*6|vitus\s*substance|substance|
 giant\s*revolt|liv\s*devote|trek\s*checkpoint|specialized\s*diverge|
 3t\s*exploro|open\s*up|open\s*wide|evil\s*chamois|chamois\s*hagar|
 santa\s*cruz\s*stigmata|stigmata|ibis\s*hakka|hakka\s*mx|
 pinarello\s*grevil|grevil|colnago\s*g3x|g3x|wilier\s*jena|jena|jaroon|
 rondo\s*ruut|ruut|cinelli\s*king\s*zydeco|zydeco|genesis\s*croix|croix\s*de\s*fer
""".replace("\n", "").replace(" ", r"\s*")


# Models whose name settles what the bike is, in the three ways that matter
# here - all of them turn up on the board wearing the word "gravel".
#
# All-road and endurance frames: road clearances, road geometry, a tyre that
# tops out around 35 mm.  A Rose Blend is not a Rose Backroad, and the ad will
# not say so.
ALLROAD_MODELS = r"""
 blend|impulso|roubaix|dolce|sequoia|synapse|defy|contend\s*ar|
 domane(?!\s*\+?gravel)|endurace|paradigm|sensium
""".replace("\n", "").replace(" ", r"\s*")

# Flat-bar fitness bikes.  Road groupset, no drop bar - and the drop bar here is
# usually inferred from the levers, so these would sail through unchallenged.
FITNESS_MODELS = r"""
 sirrus|metrix|crossfire|crossway|sl\s*road|fx\s*sport|escape|quick(?!\s*cx)
""".replace("\n", "").replace(" ", r"\s*")

# Race and time-trial frames: right groupset, wrong bike entirely.
ROAD_RACE_MODELS = r"""
 plasma|supersix|foil|emonda|madone|aeroad|ultimate|oltre|specialissima|
 addict(?!\s*gravel)|speedster(?!\s*gravel)|tarmac|venge|shiv|trinity|
 propel|tcr|aethos
""".replace("\n", "").replace(" ", r"\s*")

MODEL_FAMILIES = (("allroad", ALLROAD_MODELS), ("fitness", FITNESS_MODELS),
                  ("road-race", ROAD_RACE_MODELS))


@dataclass
class Detection:
    """A detector's answer plus the evidence for it."""

    value: str | None = None
    evidence: str | None = None

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self.value is not None


def detect_type(text: str) -> Detection:
    t = norm(text)
    for name, pat in TYPE_PATTERNS:
        m = re.search(pat, t)
        if m:
            return Detection(name, m.group(0))
    m = re.search(GRAVEL_MODELS, t)
    if m:
        return Detection("gravel", m.group(0))
    return Detection(None, None)


def detect_type_with_model(text: str) -> Detection:
    """``detect_type`` but the model name outranks the label on the ad.

    Serbian sellers list gravel bikes under "drumski/trkacki" all the time, so a
    Diverge described as a road bike should still come through as gravel.  It
    cuts the other way too, and more often: a Sirrus or a Roubaix sold as
    "gravel" is a flat-bar fitness bike and an endurance road bike wearing the
    word, and the model name is the only place the ad admits it.
    """
    t = norm(text)
    d = detect_type(text)
    for family, pattern in MODEL_FAMILIES:
        m = re.search(pattern, t)
        if m:
            ev = m.group(0).strip()
            return Detection(family, f"{ev} (listed as {d.value})" if d.value else ev)
    if d.value in ("road", "trekking", None):
        m = re.search(GRAVEL_MODELS, t)
        if m:
            return Detection("gravel", f"{m.group(0)} (listed as {d.value})")
    return d


# --------------------------------------------------------------------------
# Groupsets
# --------------------------------------------------------------------------
@dataclass
class Groupset:
    brand: str | None = None
    family: str | None = None      # "grx", "tiagra", "105", "apex", ...
    model_code: str | None = None  # "rx810", "r7000", ...
    speeds: int | None = None      # rear cogs
    chainrings: int | None = None  # 1 or 2
    tier: int = 0                  # 0 = unknown/rejected .. 5 = top
    electronic: bool = False
    evidence: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        bits = [b for b in (self.brand, self.family, self.model_code) if b]
        s = " ".join(bits).upper() if bits else "?"
        if self.chainrings and self.speeds:
            s += f" {self.chainrings}x{self.speeds}"
        elif self.speeds:
            s += f" {self.speeds}s"
        return s


# Shimano GRX model codes -> (speeds, tier).  RX8xx/RX6xx/RX4xx cover the
# mechanical range; RX815/RX825 are Di2.
GRX_CODES = {
    "rx827": (12, 5), "rx825": (12, 5), "rx822": (12, 5), "rx820": (12, 5),
    "rx825di2": (12, 5),
    "rx815": (11, 5), "rx817": (11, 5), "rx810": (11, 5), "rx812": (11, 5),
    "rx800": (11, 5), "rx610": (12, 4), "rx612": (12, 4), "rx600": (11, 4),
    "rx810di2": (11, 5),
    "rx400": (10, 3), "rx410": (10, 3),
}

# family -> (default speeds, tier, hydraulic-capable)
SHIMANO_ROAD = {
    "dura-ace": (11, 5, True), "dura ace": (11, 5, True), "duraace": (11, 5, True),
    "ultegra": (11, 5, True),
    "105": (11, 4, True),
    "grx": (11, 5, True),
    "tiagra": (10, 3, True),
    "sora": (9, 1, False),
    "claris": (8, 0, False),
}
SRAM_ROAD = {
    "red": (12, 5, True), "force": (12, 5, True), "rival": (11, 4, True),
    "apex": (11, 3, True), "s700": (11, 2, True),
}
CAMPY = {"ekar": (13, 5, True), "super record": (12, 5, True), "record": (12, 5, True),
         "chorus": (12, 5, True), "potenza": (11, 4, True), "centaur": (11, 3, True),
         "athena": (11, 3, True), "veloce": (10, 2, False)}
OTHER = {"advent x": (10, 2, False), "sword": (10, 2, False), "centos": (11, 2, False),
         "sensah": (11, 2, False), "empire": (11, 2, False), "ltwoo": (11, 2, False)}

# Shimano MTB families sometimes bolted onto drop-bar builds; tracked so the
# scout can say "this is a flat-bar group" instead of shrugging.
SHIMANO_MTB = {"deore", "slx", "xt", "xtr", "alivio", "acera", "altus", "tourney", "cues"}


def _find_speeds(t: str) -> tuple[int | None, int | None, str | None]:
    """Return ``(chainrings, speeds, evidence)`` from 2x11 / 22 brzine / 11s."""
    m = re.search(r"\b([123])\s*[xх*]\s*(\d{1,2})\b", t)
    if m:
        return int(m.group(1)), int(m.group(2)), m.group(0)
    m = re.search(r"\b(\d{1,2})\s*[xх*]\s*([123])\b", t)  # "11x2"
    if m:
        return int(m.group(2)), int(m.group(1)), m.group(0)
    m = re.search(r"\b(\d{1,2})\s*(?:brzin[aeu]?|stepen|speed|s(?:pd)?\b|-?brzinski)", t)
    if m:
        n = int(m.group(1))
        if n in (16, 18, 20, 22, 24, 26):  # total gears on a double
            return 2, n // 2, m.group(0)
        if 8 <= n <= 13:
            return None, n, m.group(0)
    return None, None, None


def detect_groupset(text: str) -> Groupset:
    t = norm(text)
    sq = squeeze(text)
    g = Groupset()
    chain, speeds, sp_ev = _find_speeds(t)
    if sp_ev:
        g.evidence.append(sp_ev)

    # GRX first: the most specific and the one we care most about.
    code = None
    for c in GRX_CODES:
        if c in sq:
            code = c
            break
    if code or re.search(r"\bgrx\b", t) or "grx" in sq:
        g.brand, g.family = "shimano", "grx"
        g.tier = 5
        if code:
            g.model_code = code
            sp, tier = GRX_CODES[code]
            g.tier = tier
            speeds = speeds or sp
            g.evidence.append(code)
        else:
            g.evidence.append("grx")
        if re.search(r"\bdi2\b", t):
            g.electronic = True
    else:
        for fam, (sp, tier, _hyd) in {**SHIMANO_ROAD}.items():
            if fam == "grx":
                continue
            pat = r"\b" + re.escape(fam) + r"\b"
            m = re.search(pat, t)
            if m:
                g.brand, g.family, g.tier = "shimano", fam, tier
                speeds = speeds or sp
                g.evidence.append(m.group(0))
                break
        if not g.family:
            for fam, (sp, tier, _h) in SRAM_ROAD.items():
                if re.search(r"\bsram\b", t) and re.search(r"\b" + fam + r"\b", t):
                    g.brand, g.family, g.tier = "sram", fam, tier
                    speeds = speeds or sp
                    g.evidence.append(f"sram {fam}")
                    break
        if not g.family:
            for fam, (sp, tier, _h) in CAMPY.items():
                if re.search(r"\b" + fam.replace(" ", r"\s*") + r"\b", t):
                    g.brand, g.family, g.tier = "campagnolo", fam, tier
                    speeds = speeds or sp
                    g.evidence.append(fam)
                    break
        if not g.family:
            for fam, (sp, tier, _h) in OTHER.items():
                if re.search(r"\b" + fam.replace(" ", r"\s*") + r"\b", t):
                    g.brand, g.family, g.tier = "other", fam, tier
                    speeds = speeds or sp
                    g.evidence.append(fam)
                    break
        if not g.family:
            for fam in SHIMANO_MTB:
                if re.search(r"\b" + fam + r"\b", t):
                    g.brand, g.family, g.tier = "shimano", fam, 1
                    g.evidence.append(fam)
                    break
    # A model code like R7000/R8000/R7020 pins the family even without a name.
    m = re.search(r"\b(r[78]0[0-9]{2}|r[78]1?[0-9]{2}|4[67][0-9]{2})\b", sq)
    if m and g.brand in (None, "shimano"):
        g.model_code = g.model_code or m.group(1)
        g.evidence.append(m.group(1))
        if not g.family:
            code_n = m.group(1)
            if code_n.startswith("r8"):
                g.brand, g.family, g.tier, speeds = "shimano", "ultegra", 5, speeds or 11
            elif code_n.startswith("r7"):
                g.brand, g.family, g.tier, speeds = "shimano", "105", 4, speeds or 11
            elif code_n.startswith("47"):
                g.brand, g.family, g.tier, speeds = "shimano", "tiagra", 3, speeds or 10

    g.speeds, g.chainrings = speeds, chain
    return g


# --------------------------------------------------------------------------
# Brakes and handlebar
# --------------------------------------------------------------------------
HYDRO = r"\bhidraul|\bhydraul|\bhidro\s*(disk|koc)|\bhidraulicne\b|\bhydro\b"
MECH_DISC = r"\bmehanic\w*\s*disk|\bmechanical\s*disc|\bbb5\b|\bbb7\b|\bspyre\b|\bavid\s*bb\b|\btektro\s*mira\b|\bsajl\w*\s*disk"
DISC = r"\bdisk\b|\bdisc\b|\bdiskovi\b|\bdisk\s*koc|\brotor\b|\bdisk-?koc"
RIM = r"\bfelnaste?\b|\bfelne\s*koc|\brim\s*brake|\bkaliper\b|\bcaliper\b|\bv-?brake\b|\bcantilever\b|\bklasicne\s*koc"


def detect_brakes(text: str) -> Detection:
    t = norm(text)
    m = re.search(MECH_DISC, t)
    if m:
        return Detection("mechanical_disc", m.group(0))
    mh = re.search(HYDRO, t)
    md = re.search(DISC, t)
    if mh:
        return Detection("hydraulic_disc", mh.group(0))
    if md:
        return Detection("disc_unknown_actuation", md.group(0))
    mr = re.search(RIM, t)
    if mr:
        return Detection("rim", mr.group(0))
    return Detection(None, None)


DROP = r"\bdrop\s*bar|\bdropbar\b|\bobarac\b|\bspusten\w*\s*volan|\btrkacki\s*volan|\bkormilo\s*trkac|\bpolukruz\w*\s*volan|\bram\s*volan\b"
FLAT = r"\bravan\s*volan|\bravno\s*kormilo|\bflat\s*bar|\bflatbar\b|\bprav\w*\s*volan"


def detect_bar(text: str) -> Detection:
    t = norm(text)
    m = re.search(DROP, t)
    if m:
        return Detection("drop", m.group(0))
    m = re.search(FLAT, t)
    if m:
        return Detection("flat", m.group(0))
    return Detection(None, None)


WOMEN = r"\bzenski\b|\bzenska\b|\bwomen\b|\bwomens\b|\bwsd\b|\blady\b|\bladies\b|\bfeminin|\bdamski\b|\bliv\b|\bwmn\b"


def detect_women(text: str) -> Detection:
    m = re.search(WOMEN, norm(text))
    return Detection("women", m.group(0)) if m else Detection(None, None)


FRAME_MATERIAL = [
    ("carbon", r"\bkarbon\w*|\bcarbon\b|\bhm\s*carbon\b"),
    ("titanium", r"\btitan\w*|\btitanium\b"),
    ("steel", r"\bcelic\w*|\bsteel\b|\bchromoly\b|\bcromoly\b|\b4130\b|\breynolds\b|\bcolumbus\b"),
    ("aluminium", r"\balumin\w*|\balu\b|\baluminij\w*|\bal[\s-]?6061\b|\bal[\s-]?7005\b"),
]


def detect_material(text: str) -> Detection:
    t = norm(text)
    for name, pat in FRAME_MATERIAL:
        m = re.search(pat, t)
        if m:
            return Detection(name, m.group(0))
    return Detection(None, None)


# --------------------------------------------------------------------------
# Bike brands
# --------------------------------------------------------------------------
# How each brand actually turns up in a Serbian ad, after ``norm`` has folded
# the Cyrillic and the diacritics.  Only brands that can be matched without
# catching something else are listed: "force" would collide with SRAM Force,
# "max" and "ultra" with ordinary adjectives, so those stay out rather than
# rejecting a good bike over a word in the description.
BIKE_BRANDS = {
    # wanted tier
    "rose": r"\brose\b(?!\s*(?:boja|zlat))",
    "giant": r"\bgiant\b",
    "liv": r"\bliv\b",
    "specialized": r"\bspecializ?ed\b|\bspesh\b",
    "scott": r"\bscott\b",
    "cannondale": r"\bcannondale\b|\bcanondale\b",
    "trek": r"\btrek\b",
    "bianchi": r"\bbianchi\b",
    "cervelo": r"\bcervelo\b",
    "bmc": r"\bbmc\b",
    "ridley": r"\bridley\b",
    "orbea": r"\borbea\b",
    "wilier": r"\bwilier\b",
    "pinarello": r"\bpinarello\b",
    "colnago": r"\bcolnago\b",
    "santa cruz": r"\bsanta\s*cruz\b",
    "niner": r"\bniner\b",
    "salsa": r"\bsalsa\b",
    "surly": r"\bsurly\b",
    "kona": r"\bkona\b",
    "marin": r"\bmarin\b",
    "fuji": r"\bfuji\b",
    "lauf": r"\blauf\b",
    "3t": r"\b3t\b",
    "open": r"\bopen\s*(?:u\.?p\.?|wi\.?de)\b",
    "ibis": r"\bibis\b",
    "rondo": r"\brondo\b",
    "cinelli": r"\bcinelli\b",
    "mason": r"\bmason\b",
    "bombtrack": r"\bbombtrack\b",
    "vitus": r"\bvitus\b",
    "basso": r"\bbasso\b",
    "look": r"\blook\s*7\d\d\b|\blook\s*(?:huez|765|785|795)\b",
    "felt": r"\bfelt\b",
    "gt": r"\bgt\s*(?:grade|avalanche|zaskar)\b",
    "norco": r"\bnorco\b",

    # neither wanted nor ruled out: detected so the ad can say so out loud
    "genesis": r"\bgenesis\b",

    # ruled out on build quality - the shop-brand tier and below
    "merida": r"\bmerida\b",
    "focus": r"\bfocus\b",
    "ghost": r"\bghost\b",
    "bergamont": r"\bbergamont\b",
    "ktm": r"\bktm\b",
    "kross": r"\bkross\b",
    "stevens": r"\bstevens\b",
    "lapierre": r"\blapierre\b",
    "cube": r"\bcube\b",
    "canyon": r"\bcanyon\b|\bkanjon\b",
    "axess": r"\baxess\b",
    "capriolo": r"\bcapriolo\b|\bkapriolo\b",
    "visitor": r"\bvisitor\b",
    "venssini": r"\bvenssini\b|\bvensini\b",
    "explorer": r"\bx?explorer\b|\bxplorer\b",
    "galaxy": r"\bgalaxy\b",
    "favorit": r"\bfavorit\b",
    "adria": r"\badria\b",
    "btwin": r"\bb\s*twin\b|\bbtwin\b",
    "rockrider": r"\brockrider\b",
    "triban": r"\btriban\b",
    "alpina": r"\balpina\b",
    "mercury": r"\bmercury\b",
    "crosswind": r"\bcrosswind\b",
}


def detect_brand(text: str) -> Detection:
    """Name the bike's maker, or return nothing rather than guess.

    The longest match wins, so "Santa Cruz" is not read as a stray "cruz" and a
    title that names both a brand and a component maker still resolves to the
    bike.
    """
    t = norm(text)
    best: tuple[int, str, str] | None = None
    for brand, pat in BIKE_BRANDS.items():
        m = re.search(pat, t)
        if m and (best is None or len(m.group(0)) > best[0]):
            best = (len(m.group(0)), brand, m.group(0))
    return Detection(best[1], best[2]) if best else Detection(None, None)
