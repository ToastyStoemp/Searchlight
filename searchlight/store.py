"""SQLite record of every listing seen and every match found."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .matcher import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    source TEXT NOT NULL,
    listing_id TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (source, listing_id)
);
CREATE TABLE IF NOT EXISTS matches (
    source TEXT NOT NULL,
    listing_id TEXT NOT NULL,
    product TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    price REAL,
    image TEXT,
    text TEXT,
    found_at TEXT NOT NULL,
    screenshot TEXT,
    PRIMARY KEY (source, listing_id, product)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def mark_seen(self, listing: Listing) -> bool:
        """Record the listing; return True if it hadn't been seen before."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO seen VALUES (?, ?, ?)",
            (listing.source, listing.listing_id, now()),
        )
        self.db.commit()
        return cur.rowcount == 1

    def add_match(self, product: str, listing: Listing) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO matches VALUES (?,?,?,?,?,?,?,?,?,NULL)",
            (
                listing.source, listing.listing_id, product, listing.url,
                listing.title, listing.price, listing.image, listing.text, now(),
            ),
        )
        self.db.commit()
        return cur.rowcount == 1

    def set_screenshot(self, listing: Listing, path: str) -> None:
        self.db.execute(
            "UPDATE matches SET screenshot=? WHERE source=? AND listing_id=?",
            (path, listing.source, listing.listing_id),
        )
        self.db.commit()

    def all_matches(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM matches ORDER BY found_at DESC").fetchall()
