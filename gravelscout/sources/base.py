"""HTTP plumbing and source-agnostic extraction helpers.

None of the Serbian classifieds publish an API, and all of them reshuffle their
markup from time to time.  So instead of pinning one set of CSS selectors per
site, each source tries three strategies in order and keeps whichever produced
the most listings:

1. embedded JSON (Next.js ``__NEXT_DATA__``, ``application/json`` islands)
2. JSON-LD ``ItemList`` / ``Product`` blocks
3. a heuristic HTML pass: find anchors that look like detail links, then climb
   to the nearest ancestor that also contains a price

Strategy 3 keeps working when the markup changes, which is the point.  Run
``python -m gravelscout dump --source <name>`` to save the raw HTML whenever a
site does change and the parsers need a look.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from ..models import Listing
from ..normalize import norm, parse_price

DEBUG_DIR = Path("debug")

# Marks of a Cloudflare interstitial rather than a real 403.  The page is a
# JavaScript challenge, so no amount of retrying or header polish gets past it;
# only a real browser does.
CHALLENGE_MARKERS = ("just a moment", "_cf_chl_opt", "cdn-cgi/challenge-platform",
                     "__cf_chl_tk", "enable javascript and cookies to continue")


@dataclass
class HttpClient:
    user_agent: str
    delay_seconds: float = 2.0
    timeout: float = 25.0
    retries: int = 3
    dump: bool = False

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
        })
        self._last_call = 0.0
        # Hosts that answered with a challenge page, and why.  A blocked host is
        # skipped for the rest of the run instead of being retried page by page.
        self.blocked: dict[str, str] = {}
        self.last_reason: str | None = None

    def is_blocked(self, url: str) -> str | None:
        """Return why *url*'s host is being skipped, or None if it is fine."""
        return self.blocked.get(urlsplit(url).netloc)

    def get(self, url: str, *, referer: str | None = None) -> str | None:
        host = urlsplit(url).netloc
        if host in self.blocked:
            self.last_reason = self.blocked[host]
            return None
        self.last_reason = None
        wait = self.delay_seconds - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        headers = {"Referer": referer} if referer else {}
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = self.session.get(url, timeout=self.timeout, headers=headers)
                self._last_call = time.monotonic()
                if r.status_code == 404:
                    self.last_reason = "HTTP 404"
                    return None
                if r.status_code in (403, 429, 503):
                    challenge = challenge_reason(r.status_code, r.headers, r.text)
                    if challenge:
                        # Retrying only wastes the crawl: remember the host and move on.
                        self.blocked[host] = challenge
                        self.last_reason = challenge
                        if self.dump:
                            self._dump(url, r.text)
                        return None
                    self.last_reason = f"HTTP {r.status_code}"
                    # Back off hard: these are "slow down" or "you look like a bot".
                    time.sleep(3 * (attempt + 1) ** 2)
                    continue
                r.raise_for_status()
                if self.dump:
                    self._dump(url, r.text)
                return r.text
            except requests.RequestException as exc:  # network hiccup, retry
                last_error = exc
                self.last_reason = f"{type(exc).__name__}: {exc}"
                self._last_call = time.monotonic()
                time.sleep(2 ** attempt)
        if last_error:
            print(f"  ! giving up on {url}: {last_error}")
        return None

    @staticmethod
    def _dump(url: str, html: str) -> None:
        DEBUG_DIR.mkdir(exist_ok=True)
        name = re.sub(r"[^a-z0-9]+", "_", url.lower())[-120:] + ".html"
        (DEBUG_DIR / name).write_text(html, encoding="utf-8")


def challenge_reason(status: int, headers, body: str) -> str | None:
    """Describe a bot-wall response, or return None for an ordinary error.

    A 403 that carries a Cloudflare challenge is not the same problem as a 403
    that says "too many requests": the first one never clears on its own, and a
    scout that keeps retrying it just makes every run three minutes longer while
    reporting nothing.  Saying so out loud also saves the reader from hunting for
    a parser bug that is not there - the parser never got a page to parse.
    """
    if headers.get("cf-mitigated") == "challenge" or any(
            m in body[:20000].lower() for m in CHALLENGE_MARKERS):
        return (f"HTTP {status}, Cloudflare challenge - the site wants a real "
                "browser, and turns down this network")
    return None


# --------------------------------------------------------------------------
# JSON strategies
# --------------------------------------------------------------------------
def iter_json_blobs(soup: BeautifulSoup) -> Iterator[dict | list]:
    """Yield every JSON object embedded in the page."""
    for tag in soup.find_all("script"):
        stype = (tag.get("type") or "").lower()
        text = tag.string or tag.get_text() or ""
        text = text.strip()
        if not text:
            continue
        if stype in ("application/json", "application/ld+json") or tag.get("id") == "__NEXT_DATA__":
            try:
                yield json.loads(text)
            except (ValueError, TypeError):
                continue
        elif "__next_f.push" in text or "__NUXT__" in text or "window.__" in text:
            # App-router flight data and Nuxt payloads: the JSON is spliced into
            # a JS statement, so scan for balanced objects instead of parsing JS.
            for obj in scan_json_objects(text):
                yield obj


def scan_json_objects(text: str, *, min_len: int = 120, limit: int = 40):
    """Yield top-level ``{...}`` blocks from a JS blob, largest first.

    Only balanced, quote-aware candidates that actually parse are returned, so a
    stray brace inside a string cannot derail the scan.
    """
    found: list[str] = []
    depth = 0
    start = -1
    in_str = False
    quote = ""
    escaped = False
    for i, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                in_str = False
            continue
        if ch in "\"'":
            in_str, quote = True, ch
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
                if depth == 0 and start >= 0 and i - start >= min_len:
                    found.append(text[start:i + 1])
    found.sort(key=len, reverse=True)
    for cand in found[:limit]:
        try:
            yield json.loads(cand)
        except ValueError:
            continue


def walk(obj, path: str = "") -> Iterator[tuple[str, dict]]:
    """Depth-first walk yielding every dict inside a JSON structure."""
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


_ID_KEYS = ("adid", "id", "adid", "oglasid", "listingid", "uuid", "slug")
_TITLE_KEYS = ("name", "title", "adname", "naziv", "heading", "adtitle")
_PRICE_KEYS = ("price", "cena", "priceformatted", "pricevalue", "amount", "displayprice")
_URL_KEYS = ("url", "link", "href", "adurl", "permalink", "canonicalurl", "slug")


def _pick(d: dict, keys: Iterable[str]):
    lowered = {str(k).lower().replace("_", ""): v for k, v in d.items()}
    for k in keys:
        if k in lowered and lowered[k] not in (None, "", [], {}):
            return lowered[k]
    return None


def looks_like_ad(d: dict) -> bool:
    """A dict is ad-shaped if it has a title, an id and a price-ish field."""
    if not isinstance(d, dict) or len(d) < 3:
        return False
    title = _pick(d, _TITLE_KEYS)
    if not isinstance(title, str) or len(title) < 4:
        return False
    has_id = _pick(d, _ID_KEYS) is not None
    has_price = _pick(d, _PRICE_KEYS) is not None
    has_url = _pick(d, _URL_KEYS) is not None
    return has_id and (has_price or has_url)


def ads_from_json(soup: BeautifulSoup) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for blob in iter_json_blobs(soup):
        for _path, d in walk(blob):
            if looks_like_ad(d):
                marker = json.dumps(
                    [_pick(d, _ID_KEYS), _pick(d, _TITLE_KEYS)], ensure_ascii=False, default=str)
                if marker not in seen:
                    seen.add(marker)
                    out.append(d)
    return out


def listing_from_json(d: dict, *, source: str, base_url: str,
                      rsd_per_eur: float) -> Listing | None:
    title = _pick(d, _TITLE_KEYS)
    if not isinstance(title, str):
        return None
    raw_id = _pick(d, _ID_KEYS)
    url = _pick(d, _URL_KEYS)
    if isinstance(url, dict):
        url = url.get("url") or url.get("href")
    if not isinstance(url, str):
        url = ""
    url = urljoin(base_url, url) if url else ""

    price_field = _pick(d, _PRICE_KEYS)
    if isinstance(price_field, dict):
        price_field = (price_field.get("value") or price_field.get("amount")
                       or price_field.get("formatted") or json.dumps(price_field))
    price_eur, price_raw = parse_price(str(price_field) if price_field is not None else None,
                                       rsd_per_eur)
    # A currency field next to the number beats the guess made by parse_price.
    cur = _pick(d, ("currency", "currencycode", "valuta"))
    if price_eur is not None and isinstance(cur, str):
        c = cur.strip().lower()
        if c in ("rsd", "din", "dinar") and price_raw and "din" not in price_raw:
            price_eur = round(price_eur / rsd_per_eur, 2)
        elif c in ("eur", "euro", "€") and price_raw and "din" in price_raw:
            price_eur = round(price_eur * rsd_per_eur, 2)

    images = []
    for key in ("images", "imageurls", "photos", "slike", "image", "thumbnail", "imageurl"):
        v = _pick(d, (key,))
        if isinstance(v, str):
            images.append(urljoin(base_url, v))
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    images.append(urljoin(base_url, item))
                elif isinstance(item, dict):
                    u = item.get("url") or item.get("src") or item.get("path")
                    if isinstance(u, str):
                        images.append(urljoin(base_url, u))
        if images:
            break

    desc = _pick(d, ("description", "opis", "text", "body", "shortdescription")) or ""
    loc = _pick(d, ("location", "city", "grad", "place", "locationname", "mesto"))
    if isinstance(loc, dict):
        loc = loc.get("name") or loc.get("city")
    posted = _pick(d, ("renewdate", "publisheddate", "date", "createdat", "datum", "time", "posted"))

    return Listing(
        source=source, source_id=str(raw_id), url=url, title=title.strip(),
        description=str(desc)[:4000], price_eur=price_eur, price_raw=str(price_field or "")[:60],
        location=str(loc) if loc else None,
        posted_raw=str(posted) if posted else None,
        images=images[:8], raw={"json_keys": sorted(d.keys())[:40]},
    )


# --------------------------------------------------------------------------
# Heuristic HTML strategy
# --------------------------------------------------------------------------
# Anchored on the currency and with no whitespace inside the number, so a
# frame size printed just before the price is not absorbed into it.
_PRICE_TEXT = re.compile(
    r"(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(?:€|eur\b|din\w*|rsd\b|e\b)",
    re.IGNORECASE)


def ads_from_html(soup: BeautifulSoup, *, source: str, base_url: str,
                  detail_re: re.Pattern[str], rsd_per_eur: float) -> list[Listing]:
    """Find detail links, then climb to the nearest ancestor holding a price."""
    out: dict[str, Listing] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not detail_re.search(href):
            continue
        url = urljoin(base_url, href.split("#")[0])
        title = norm_title(a)
        node = a
        price_eur = price_raw = None
        image = None
        location = None
        for _ in range(5):  # climb a few levels looking for the card
            node = node.parent
            if node is None:
                break
            block = node.get_text(" ", strip=True)
            if price_eur is None:
                m = _PRICE_TEXT.search(block)
                if m:
                    price_eur, price_raw = parse_price(m.group(0), rsd_per_eur)
            if image is None:
                img = node.find("img")
                if img:
                    src = (img.get("src") or img.get("data-src") or img.get("data-original")
                           or img.get("data-lazy") or "")
                    if src and not src.startswith("data:"):
                        image = urljoin(base_url, src)
                    if not title:
                        title = (img.get("alt") or "").strip()
            if price_eur is not None and image is not None:
                break
        if not title:
            continue
        prev = out.get(url)
        cand = Listing(
            source=source, source_id=extract_id(url) or url, url=url, title=title,
            price_eur=price_eur, price_raw=price_raw, location=location,
            images=[image] if image else [], raw={"strategy": "html"},
        )
        # Keep the richest version of a URL that appears several times on a page.
        if prev is None or _richness(cand) > _richness(prev):
            out[url] = cand
    return list(out.values())


def norm_title(a) -> str:
    title = a.get_text(" ", strip=True)
    if len(title) < 4:
        title = (a.get("title") or a.get("aria-label") or "").strip()
    return re.sub(r"\s+", " ", title)[:200]


def _richness(l: Listing) -> int:
    return (2 if l.price_eur else 0) + (1 if l.images else 0) + min(len(l.title) // 20, 3)


_ID_IN_URL = re.compile(r"(?:oglas|ad|item|listing|p)[/\-_](\d{4,})|/(\d{6,})(?:\D|$)")


def extract_id(url: str) -> str | None:
    m = _ID_IN_URL.search(url)
    if m:
        return m.group(1) or m.group(2)
    m = re.search(r"(\d{5,})", url)
    return m.group(1) if m else None


class Source:
    """Base class: a source builds page URLs and parses whatever comes back."""

    name = "base"
    base_url = ""
    detail_re = re.compile(r"$^")

    def __init__(self, cfg: dict, http: HttpClient, rsd_per_eur: float = 117.0):
        self.cfg = cfg or {}
        self.http = http
        self.rsd_per_eur = rsd_per_eur

    # Sources override this.
    def page_urls(self) -> Iterator[tuple[str, str]]:
        """Yield ``(category_name, url)`` for every search page to crawl."""
        raise NotImplementedError

    def parse_page(self, html: str, url: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        from_json = []
        for d in ads_from_json(soup):
            l = listing_from_json(d, source=self.name, base_url=self.base_url,
                                  rsd_per_eur=self.rsd_per_eur)
            if l and l.title and (l.url or l.source_id):
                if not l.url:
                    continue
                if self.detail_re.search(l.url):
                    from_json.append(l)
        from_html = ads_from_html(soup, source=self.name, base_url=self.base_url,
                                  detail_re=self.detail_re, rsd_per_eur=self.rsd_per_eur)
        # Prefer whichever strategy saw more of the page, then merge in the rest.
        primary, secondary = ((from_json, from_html) if len(from_json) >= len(from_html)
                              else (from_html, from_json))
        by_url = {l.url: l for l in primary}
        for l in secondary:
            if l.url not in by_url:
                by_url[l.url] = l
            else:
                merge(by_url[l.url], l)
        return list(by_url.values())

    def fetch_detail(self, listing: Listing) -> Listing:
        """Load the ad page and fill in the full description and photos."""
        html = self.http.get(listing.url, referer=self.base_url)
        if not html:
            return listing
        soup = BeautifulSoup(html, "lxml")
        listing.detail_fetched = True
        for d in ads_from_json(soup):
            full = listing_from_json(d, source=self.name, base_url=self.base_url,
                                     rsd_per_eur=self.rsd_per_eur)
            if full and norm(full.title)[:30] == norm(listing.title)[:30]:
                merge(listing, full)
        if len(listing.description) < 40:
            listing.description = extract_description(soup)
        if len(listing.images) < 2:
            listing.images = extract_images(soup, self.base_url) or listing.images
        listing.raw.setdefault("attributes", {}).update(extract_attributes(soup))
        return listing

    def crawl(self, max_pages: int | None = None) -> list[Listing]:
        seen: dict[str, Listing] = {}
        for category, url in self.page_urls():
            html = self.http.get(url, referer=self.base_url)
            if not html:
                print(f"  - {self.name}: {self.http.last_reason or 'no response'} <{url}>")
                if self.http.is_blocked(url):
                    break  # the rest of this site's pages will say the same thing
                continue
            found = self.parse_page(html, url)
            print(f"  - {self.name}: {len(found):>3} listings from {category} <{url}>")
            for l in found:
                l.category = l.category or category
                if l.url in seen:
                    merge(seen[l.url], l)
                else:
                    seen[l.url] = l
        return list(seen.values())


def merge(target: Listing, other: Listing) -> None:
    """Fill gaps in *target* from *other* without overwriting good data."""
    if len(other.title) > len(target.title):
        target.title = other.title
    if len(other.description) > len(target.description):
        target.description = other.description
    if target.price_eur is None and other.price_eur is not None:
        target.price_eur, target.price_raw = other.price_eur, other.price_raw
    target.location = target.location or other.location
    target.posted_raw = target.posted_raw or other.posted_raw
    target.seller = target.seller or other.seller
    if other.source_id and (not target.source_id or target.source_id.startswith("http")):
        target.source_id = other.source_id
    for img in other.images:
        if img not in target.images:
            target.images.append(img)
    target.images = target.images[:8]
    for k, v in (other.raw or {}).items():
        target.raw.setdefault(k, v)


def extract_description(soup: BeautifulSoup) -> str:
    for sel in ('meta[property="og:description"]', 'meta[name="description"]'):
        m = soup.select_one(sel)
        if m and m.get("content") and len(m["content"]) > 60:
            return m["content"].strip()[:4000]
    best = ""
    for node in soup.find_all(["div", "section", "article", "p"]):
        cls = " ".join(node.get("class") or []) + " " + (node.get("id") or "")
        if re.search(r"descr|opis|detail|content|text|body", cls, re.I):
            txt = node.get_text("\n", strip=True)
            if len(txt) > len(best):
                best = txt
    if not best:
        best = soup.get_text("\n", strip=True)
    return best[:4000]


def extract_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    og = soup.select_one('meta[property="og:image"]')
    if og and og.get("content"):
        urls.append(urljoin(base_url, og["content"]))
    for img in soup.find_all("img"):
        src = (img.get("src") or img.get("data-src") or img.get("data-original")
               or img.get("data-lazy") or "")
        if not src or src.startswith("data:"):
            continue
        if re.search(r"logo|icon|sprite|avatar|placeholder|banner", src, re.I):
            continue
        u = urljoin(base_url, src)
        if u not in urls:
            urls.append(u)
    return urls[:8]


def extract_attributes(soup: BeautifulSoup) -> dict:
    """Pull the key/value spec table that most classifieds render on ad pages."""
    attrs: dict[str, str] = {}
    for row in soup.find_all(["tr", "li", "div"]):
        cells = row.find_all(["th", "td", "span", "strong", "b"], recursive=False)
        if len(cells) == 2:
            k = cells[0].get_text(" ", strip=True)
            v = cells[1].get_text(" ", strip=True)
            if 2 <= len(k) <= 40 and 1 <= len(v) <= 120 and k != v:
                attrs[k] = v
        if len(attrs) > 60:
            break
    return attrs
