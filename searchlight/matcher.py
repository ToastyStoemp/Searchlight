"""Decide whether a scraped listing looks like one of the stolen items."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

PRICE_RE = re.compile(
    r"(?:CHF|Fr\.?|SFr\.?)\s*([\d'’ .,]+\d)|([\d'’ .,]*\d)(?:\.-|\.–|,-)?\s*(?:CHF|Fr\.)",
    re.IGNORECASE,
)
# Swiss price without a currency label, as Ricardo and tutti print it:
# "1'450.00", "1'300.-", "80.–".
BARE_PRICE_RE = re.compile(r"(?<![\d.,'’])(\d{1,3}(?:['’]\d{3})+|\d+)\.(?:-|–|\d{2})(?![\d])")


@dataclass
class Product:
    name: str
    # Each entry is a phrase; a listing matches when every word of at least
    # one phrase appears in its text (order and spacing don't matter).
    keywords: list[str]
    # Search terms sent to the marketplaces. Defaults to `keywords`.
    queries: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    min_price: float | None = None
    max_price: float | None = None

    def __post_init__(self):
        if not self.keywords:
            raise ValueError(f"Product '{self.name}' needs at least one keyword")
        if not self.queries:
            self.queries = list(self.keywords)


@dataclass
class Listing:
    source: str
    listing_id: str
    url: str
    text: str
    image: str = ""

    @property
    def title(self) -> str:
        lines = [l.strip() for l in self.text.splitlines() if l.strip()]
        # The longest of the first few lines is almost always the title;
        # shorter ones tend to be prices, dates and locations.
        return max(lines[:4], key=len) if lines else self.url

    @property
    def price(self) -> float | None:
        return parse_price(self.text)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _contains_phrase(haystack: str, phrase: str) -> bool:
    words = set(haystack.split())
    joined = haystack.replace(" ", "")
    for word in normalise(phrase).split():
        # Allow "m2" to match "M2" and "a2338" to match "A2338" inside
        # longer model strings, but avoid tiny-word substring hits.
        if word in words:
            continue
        if len(word) >= 4 and word in joined:
            continue
        return False
    return True


def parse_price(text: str) -> float | None:
    for m in PRICE_RE.finditer(text):
        raw = (m.group(1) or m.group(2) or "").strip()
        raw = re.sub(r"['’ ]", "", raw)
        # "1.299,50" / "1,299.50" / "1299.-"
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
        elif "," in raw:
            raw = raw.replace(",", ".") if len(raw.split(",")[-1]) == 2 else raw.replace(",", "")
        elif raw.count(".") > 1 or (raw.count(".") == 1 and len(raw.split(".")[-1]) == 3):
            raw = raw.replace(".", "")
        try:
            return float(raw)
        except ValueError:
            continue
    m = BARE_PRICE_RE.search(text)
    if m:
        return float(re.sub(r"['’]", "", m.group(1)))
    return None


def matches(product: Product, listing: Listing) -> bool:
    text = normalise(listing.text)
    if not any(_contains_phrase(text, kw) for kw in product.keywords):
        return False
    if any(_contains_phrase(text, ex) for ex in product.exclude):
        return False
    price = listing.price
    if price is not None:
        if product.min_price is not None and price < product.min_price:
            return False
        if product.max_price is not None and price > product.max_price:
            return False
    return True
