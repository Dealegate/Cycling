"""Polovni Automobili - car site with a busy bicycle section."""
from __future__ import annotations

from typing import Iterator

from .base import Source
from .matcher import LinkMatcher


class PolovniAutomobili(Source):
    name = "polovniautomobili"
    base_url = "https://www.polovniautomobili.com"
    detail_re = LinkMatcher(
        include=r"/bicikli/\d+/|/bicikl-oglas/\d+|/oglas/\d+",
        exclude=r"/bicikli/?$|/bicikli\?",
    )

    def page_urls(self) -> Iterator[tuple[str, str]]:
        pages = int(self.cfg.get("pages", 2))
        path = self.cfg.get("path", "/bicikli")
        for n in range(1, pages + 1):
            yield "Bicikli", f"{self.base_url}{path}?page={n}&sort=renewDate_desc"
