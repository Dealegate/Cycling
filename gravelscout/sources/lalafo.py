"""Lalafo.rs - app-first classifieds, a lot of bikes, patchy descriptions."""
from __future__ import annotations

from typing import Iterator

from .base import Source
from .matcher import LinkMatcher


class Lalafo(Source):
    name = "lalafo"
    base_url = "https://lalafo.rs"
    detail_re = LinkMatcher(include=r"/[a-z-]+/ad/|-id-\d+", exclude=r"/q-|/used/?$")

    def page_urls(self) -> Iterator[tuple[str, str]]:
        pages = int(self.cfg.get("pages", 2))
        for n in range(1, pages + 1):
            yield "Bicikli", f"{self.base_url}/serbia/bicikli?page={n}"
