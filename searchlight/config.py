from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .matcher import Product
from .sources import Source, build_sources


@dataclass
class Config:
    products: list[Product]
    sources: list[Source]
    data_dir: Path
    interval_minutes: float = 20
    headless: bool = False
    facebook_location: str = "zurich"
    screenshot_matches: bool = True
    notify: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "searchlight.db"

    @property
    def profile_dir(self) -> Path:
        return self.data_dir / "browser-profile"

    @property
    def evidence_dir(self) -> Path:
        return self.data_dir / "evidence"


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    products = [
        Product(
            name=p["name"],
            keywords=p.get("keywords", []),
            queries=p.get("queries", []),
            exclude=p.get("exclude", []),
            min_price=p.get("min_price"),
            max_price=p.get("max_price"),
        )
        for p in raw.get("products", [])
    ]
    if not products:
        raise ValueError(f"{path}: add at least one entry under `products:`")

    enabled = raw.get("enabled_sources", ["ricardo", "tutti", "anibis", "facebook"])
    data_dir = Path(raw.get("data_dir", "~/.searchlight")).expanduser()
    if not data_dir.is_absolute():
        data_dir = (path.parent / data_dir).resolve()

    return Config(
        products=products,
        sources=build_sources(enabled, raw.get("sources", {}) or {}),
        data_dir=data_dir,
        interval_minutes=float(raw.get("interval_minutes", 20)),
        headless=bool(raw.get("headless", False)),
        facebook_location=str(raw.get("facebook_location", "zurich")),
        screenshot_matches=bool(raw.get("screenshot_matches", True)),
        notify=raw.get("notify", {}) or {},
    )
