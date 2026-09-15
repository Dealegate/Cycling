"""Link matching with an exclusion list.

Several of these sites build category URLs that look exactly like detail URLs
(`.../gravel-ciklokros-189` is a category, `.../neki-bicikl-44231` is an ad), so
matching needs both an include and an exclude pattern.
"""
from __future__ import annotations

import re


class LinkMatcher:
    def __init__(self, include: str, exclude: str | None = None):
        self.include = re.compile(include, re.IGNORECASE)
        self.exclude = re.compile(exclude, re.IGNORECASE) if exclude else None

    def search(self, href: str):
        if self.exclude and self.exclude.search(href):
            return None
        return self.include.search(href)

    def __repr__(self) -> str:  # pragma: no cover
        return f"LinkMatcher(include={self.include.pattern!r}, exclude={self.exclude.pattern if self.exclude else None!r})"
