"""Configuration loading, with the derived fit window in one place."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .geometry import FitWindow, GeometryDB
from .sizing import SizeWindow, max_standover_mm, saddle_height_range

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"


@dataclass
class Config:
    raw: dict
    path: Path

    @classmethod
    def load(cls, path: Path | str = DEFAULT_CONFIG) -> "Config":
        p = Path(path)
        return cls(raw=yaml.safe_load(p.read_text(encoding="utf-8")) or {}, path=p)

    def __getitem__(self, key):
        return self.raw[key]

    def get(self, key, default=None):
        return self.raw.get(key, default)

    # -- derived views -----------------------------------------------------
    @property
    def size_window(self) -> SizeWindow:
        s = self.raw.get("size", {})
        return SizeWindow(cm_min=s.get("cm_min", 47), cm_max=s.get("cm_max", 52),
                          letters=tuple(s.get("letters", ["xxs", "xs", "s"])))

    def fit_window(self, db: GeometryDB) -> FitWindow:
        f = self.raw.get("fit", {})
        inseam = self.raw.get("rider", {}).get("inseam_cm", [80, 82])
        return FitWindow.from_anchor(
            db.anchor,
            stack_tol=f.get("stack_tolerance_mm", 28),
            reach_tol=f.get("reach_tolerance_mm", 18),
            standover_max=max_standover_mm(min(inseam), f.get("standover_clearance_mm", 20)),
            seat_tube_max=f.get("seat_tube_max_mm"),
        )

    @property
    def saddle_height_mm(self) -> tuple[float, float]:
        inseam = self.raw.get("rider", {}).get("inseam_cm", [80, 82])
        return saddle_height_range(min(inseam), max(inseam))

    @property
    def rsd_per_eur(self) -> float:
        return float(self.raw.get("price", {}).get("rsd_per_eur", 117.0))
