"""2bike.rs / Cikloberza - the Serbian cycling-only classifieds board.

The most useful board of the lot, because it has a dedicated
"Gravel/Ciklokros" category (id 189) and sellers there describe groupsets
properly.  Category URLs end in `-<id>` exactly like ad URLs do, so the link
matcher has to exclude the known category slugs.
"""
from __future__ import annotations

from typing import Iterator
from urllib.parse import quote_plus

from .base import Source
from .matcher import LinkMatcher

DEFAULT_CATEGORIES = [
    {"name": "Gravel/Ciklokros", "path": "/cikloberza/mali-oglasi/bicikli-6/gravel-ciklokros-189"},
    {"name": "Drumski trkacki", "path": "/cikloberza/mali-oglasi/bicikli-6/drumski-trkacki-8"},
]

# Category and navigation slugs that must never be mistaken for an ad.
_CATEGORY_SLUGS = (
    r"bicikli-6|mtb-bicikli-7|drumski-trkacki-8|city-turing-10|elektricni-bicikli-13|"
    r"gravel-ciklokros-189|delovi-20|ramovi-21|ramovi-i-delovi-za-ram-181|"
    r"oprema-\d+|odeca-i-obuca-\d+|alat-i-odrzavanje-\d+|ostalo-\d+"
)


class DvaBike(Source):
    name = "2bike"
    base_url = "https://www.2bike.rs"
    detail_re = LinkMatcher(
        include=r"/cikloberza/(?:mali-oglasi/)?.+?[-/]\d+/?$|/cikloberza/oglas/",
        exclude=rf"(?:{_CATEGORY_SLUGS})/?$|/cikloberza/mali-oglasi/u/|[?&]page=",
    )

    def page_urls(self) -> Iterator[tuple[str, str]]:
        pages = int(self.cfg.get("pages", 3))
        for cat in self.cfg.get("categories") or DEFAULT_CATEGORIES:
            for n in range(1, pages + 1):
                sep = "&" if "?" in cat["path"] else "?"
                url = f"{self.base_url}{cat['path']}"
                if n > 1:
                    url = f"{url}{sep}page={n}"
                yield cat["name"], url
        for kw in self.cfg.get("keywords") or []:
            yield (f"search:{kw}",
                   f"{self.base_url}/cikloberza/mali-oglasi/bicikli-6?keywords={quote_plus(kw)}")
