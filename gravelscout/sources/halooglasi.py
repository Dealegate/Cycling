"""Halo oglasi - sport & recreation section."""
from __future__ import annotations

from typing import Iterator

from .base import Source
from .matcher import LinkMatcher


class HaloOglasi(Source):
    name = "halooglasi"
    base_url = "https://www.halooglasi.com"
    detail_re = LinkMatcher(include=r"/sport-i-rekreacija/[a-z-]+/[^/]+/\d+", exclude=r"\?page=")

    def page_urls(self) -> Iterator[tuple[str, str]]:
        pages = int(self.cfg.get("pages", 2))
        for cat in self.cfg.get("categories") or [
            {"name": "Drumski bicikli", "path": "/sport-i-rekreacija/drumski-bicikli"},
            {"name": "Ostali bicikli", "path": "/sport-i-rekreacija/ostali-bicikli"},
        ]:
            for n in range(1, pages + 1):
                yield cat["name"], f"{self.base_url}{cat['path']}?page={n}"
