from __future__ import annotations

import os
import sys
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
    interval_minutes: float = 90
    # Only search between these hours (local time).
    active_hours: tuple[int, int] = (7, 23)
    # Random pause between two searches, in seconds, to keep the load light.
    search_delay_seconds: tuple[float, float] = (20, 75)
    headless: bool = False
    # How long a captcha stays on screen for you to solve before the site is
    # skipped for this run (only when a browser window is visible).
    captcha_wait_minutes: float = 10
    # After a site blocks us, leave it alone for this many hours, doubling
    # on each further block (capped at 24 h).
    block_cooldown_hours: float = 2
    facebook_location: str = "zurich"
    backup_matches: bool = True
    notify: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "searchlight.db"

    @property
    def profile_dir(self) -> Path:
        return self.data_dir / "browser-profile"

    @property
    def session_file(self) -> Path:
        return self.data_dir / "session.json"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"


def has_display() -> bool:
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


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

    # "auto": show the window when there's a screen, run headless on a server.
    headless = raw.get("headless", "auto")
    headless = not has_display() if headless == "auto" else bool(headless)

    return Config(
        products=products,
        sources=build_sources(enabled, raw.get("sources", {}) or {}),
        data_dir=data_dir,
        interval_minutes=float(raw.get("interval_minutes", 90)),
        active_hours=_pair(raw.get("active_hours", [7, 23]), int),
        search_delay_seconds=_pair(raw.get("search_delay_seconds", [20, 75]), float),
        headless=headless,
        captcha_wait_minutes=float(raw.get("captcha_wait_minutes", 10)),
        block_cooldown_hours=float(raw.get("block_cooldown_hours", 2)),
        facebook_location=str(raw.get("facebook_location", "zurich")),
        # `screenshot_matches` is the older name for this setting.
        backup_matches=bool(raw.get("backup_matches", raw.get("screenshot_matches", True))),
        notify=raw.get("notify", {}) or {},
    )


def _pair(value, cast) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"Expected a [from, to] pair, got {value!r}")
    return cast(value[0]), cast(value[1])
