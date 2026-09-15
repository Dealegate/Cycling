"""KupujemProdajem - by far the biggest Serbian classifieds site.

Bicycles live under category 912.  The groups that matter here are
919 "Drumski, trkacki" (where gravel bikes are almost always posted) and
928 "Ostali bicikli".  Category pages paginate as `.../grupa/912/919/<n>`;
free-text search is `/pretraga?keywords=...`.
"""
from __future__ import annotations

from typing import Iterator
from urllib.parse import quote_plus

from .base import Source
from .matcher import LinkMatcher

DEFAULT_CATEGORIES = [
    {"name": "Drumski, trkacki", "path": "/bicikli/drumski-trkacki/grupa/912/919"},
    {"name": "Ostali bicikli", "path": "/bicikli/ostali-bicikli/grupa/912/928"},
]


class KupujemProdajem(Source):
    name = "kupujemprodajem"
    base_url = "https://www.kupujemprodajem.com"
    detail_re = LinkMatcher(r"/oglas/\d+")

    def page_urls(self) -> Iterator[tuple[str, str]]:
        pages = int(self.cfg.get("pages", 5))
        # A keyword search rarely fills two pages - "ciklokros" and "cyclocross"
        # come back with two hits and none - so depth goes into the category
        # listings and breadth into the keyword list.
        kw_pages = int(self.cfg.get("keyword_pages", 2))
        for cat in self.cfg.get("categories") or DEFAULT_CATEGORIES:
            for n in range(1, pages + 1):
                yield cat["name"], f"{self.base_url}{cat['path']}/{n}"
        # Search runs across category 912 as a whole, which is how ads filed
        # under touring, trekking or MTB by mistake still get seen.
        for kw in self.cfg.get("keywords") or []:
            for n in range(1, kw_pages + 1):
                yield (f"search:{kw}",
                       f"{self.base_url}/pretraga?keywords={quote_plus(kw)}"
                       f"&categoryId=912&page={n}")
