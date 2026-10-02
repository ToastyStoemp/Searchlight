"""SQLite record of every listing seen and every match found."""

from __future__ import annotations

import sqlite3
import time
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
    backup_dir TEXT,
    PRIMARY KEY (source, listing_id, product)
);
CREATE TABLE IF NOT EXISTS source_state (
    source TEXT PRIMARY KEY,
    strikes INTEGER NOT NULL DEFAULT 0,
    blocked_until REAL NOT NULL DEFAULT 0
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
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(matches)")}
        if "backup_dir" not in columns:  # database from an older version
            self.db.execute("ALTER TABLE matches ADD COLUMN backup_dir TEXT")

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
            "INSERT OR IGNORE INTO matches (source, listing_id, product, url, title, price,"
            " image, text, found_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                listing.source, listing.listing_id, product, listing.url,
                listing.title, listing.price, listing.image, listing.text, now(),
            ),
        )
        self.db.commit()
        return cur.rowcount == 1

    def set_backup(self, listing: Listing, folder: str, screenshot: str | None) -> None:
        self.db.execute(
            "UPDATE matches SET backup_dir=?, screenshot=? WHERE source=? AND listing_id=?",
            (folder, screenshot, listing.source, listing.listing_id),
        )
        self.db.commit()

    # --- per-site back-off after captchas / blocks -------------------------

    def blocked_until(self, source: str) -> float:
        row = self.db.execute("SELECT blocked_until FROM source_state WHERE source=?", (source,)).fetchone()
        return row["blocked_until"] if row else 0.0

    def record_block(self, source: str, base_hours: float) -> float:
        """Note a block and return the epoch time until which to skip the site."""
        row = self.db.execute("SELECT strikes FROM source_state WHERE source=?", (source,)).fetchone()
        strikes = (row["strikes"] if row else 0) + 1
        until = time.time() + min(base_hours * 2 ** (strikes - 1), 24) * 3600
        self.db.execute(
            "INSERT INTO source_state VALUES (?,?,?) ON CONFLICT(source) DO UPDATE "
            "SET strikes=excluded.strikes, blocked_until=excluded.blocked_until",
            (source, strikes, until),
        )
        self.db.commit()
        return until

    def record_success(self, source: str) -> None:
        self.db.execute("DELETE FROM source_state WHERE source=?", (source,))
        self.db.commit()

    def all_matches(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM matches ORDER BY found_at DESC").fetchall()
