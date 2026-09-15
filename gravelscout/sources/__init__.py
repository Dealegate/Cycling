"""Source registry."""
from __future__ import annotations

from .base import HttpClient, Source
from .kupujemprodajem import KupujemProdajem
from .dvabike import DvaBike
from .polovniautomobili import PolovniAutomobili
from .lalafo import Lalafo
from .halooglasi import HaloOglasi

REGISTRY: dict[str, type[Source]] = {
    KupujemProdajem.name: KupujemProdajem,
    DvaBike.name: DvaBike,
    PolovniAutomobili.name: PolovniAutomobili,
    Lalafo.name: Lalafo,
    HaloOglasi.name: HaloOglasi,
}


def build_sources(cfg, http: HttpClient) -> list[Source]:
    out = []
    for name, scfg in (cfg.get("sources") or {}).items():
        cls = REGISTRY.get(name)
        if cls is None:
            print(f"  ! unknown source in config: {name}")
            continue
        if not (scfg or {}).get("enabled", True):
            continue
        out.append(cls(scfg, http, rsd_per_eur=cfg.rsd_per_eur))
    return out


__all__ = ["REGISTRY", "build_sources", "HttpClient", "Source"]
