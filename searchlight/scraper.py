"""Load search pages in a real browser and pull listing cards out of them.

A real (persistent) Chromium profile is used rather than plain HTTP requests
because Ricardo, tutti and Facebook all sit behind bot protection, and
Facebook Marketplace needs you to be logged in. Captchas you solve and logins
you make in `searchlight login` are remembered in that profile.
"""

from __future__ import annotations

import logging
import os
import random
import re
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, Page, sync_playwright

from .matcher import Listing
from .sources import Source

log = logging.getLogger(__name__)


class Blocked(Exception):
    """The site served a captcha / login wall instead of results."""


# For every link matching the pattern, climb to the largest ancestor that still
# contains only that one listing: that's the result "card", whose text holds
# the title, price and location.
EXTRACT_JS = r"""
(pattern) => {
  const re = new RegExp(pattern);
  const out = new Map();
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href');
    const m = href.match(re);
    if (!m) continue;
    const id = m[1];
    let card = a;
    while (card.parentElement && card.parentElement !== document.body) {
      const ids = new Set();
      for (const other of card.parentElement.querySelectorAll('a[href]')) {
        const om = other.getAttribute('href').match(re);
        if (om) ids.add(om[1]);
      }
      if (ids.size > 1) break;
      card = card.parentElement;
    }
    // One line per text node: innerText runs inline elements together
    // ("CHF1,350MacBook Pro"), which breaks both matching and pricing.
    const parts = [];
    const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const t = walker.currentNode.textContent.trim();
      if (t) parts.push(t);
    }
    const text = parts.join('\n') || a.getAttribute('aria-label') || '';
    const img = card.querySelector('img');
    const prev = out.get(id);
    if (!prev || text.length > prev.text.length) {
      out.set(id, {id, href, text, image: img ? (img.currentSrc || img.src || '') : ''});
    }
  }
  return [...out.values()];
}
"""


def extract_listings(page: Page, source: Source) -> list[Listing]:
    raw = page.evaluate(EXTRACT_JS, source.link_pattern)
    listings = []
    for item in raw:
        url = urljoin(source.base_url, item["href"]).split("?")[0]
        listings.append(Listing(source.name, item["id"], url, item["text"], item["image"]))
    return listings


class Browser:
    def __init__(self, profile_dir: Path, headless: bool, slow: bool = True):
        self.profile_dir = profile_dir
        self.headless = headless
        self.slow = slow
        self._pw = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "Browser":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            str(self.profile_dir),
            headless=self.headless,
            # Optional: use an already-installed Chrome/Chromium binary.
            executable_path=os.environ.get("SEARCHLIGHT_CHROMIUM") or None,
            locale="de-CH",
            timezone_id="Europe/Zurich",
            viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        return self

    def __exit__(self, *exc):
        if self.context:
            self.context.close()
        if self._pw:
            self._pw.stop()

    def _pause(self, page: Page, lo: float, hi: float) -> None:
        if self.slow:
            page.wait_for_timeout(random.uniform(lo, hi) * 1000)

    def search(self, source: Source, query: str, location: str = "") -> list[Listing]:
        url = source.url_for(query, location)
        page = self.context.new_page()
        try:
            log.info("[%s] %s", source.name, url)
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass  # some sites never go idle; what's loaded is enough
            self._pause(page, 1.5, 3.5)
            # Scroll a little so lazily-rendered cards (Facebook) appear.
            for _ in range(3):
                page.mouse.wheel(0, 2500)
                self._pause(page, 0.8, 1.6)

            listings = extract_listings(page, source)
            if not listings:
                title = page.title()
                body = page.content()
                if any(marker in title or marker in body for marker in source.block_markers):
                    raise Blocked(
                        f"{source.name} is showing a captcha or login page. "
                        "Run `python -m searchlight login` and solve it in the browser window."
                    )
            log.info("[%s] %d listings for %r", source.name, len(listings), query)
            return listings
        finally:
            page.close()

    def screenshot(self, url: str, path: Path) -> bool:
        page = self.context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            self._pause(page, 2, 3)
            path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(path), full_page=True)
            return True
        except Exception as exc:
            log.error("Screenshot of %s failed: %s", url, exc)
            return False
        finally:
            page.close()

    def open_for_login(self, urls: list[str]) -> None:
        for url in urls:
            self.context.new_page().goto(url)
        input(
            "\nA browser window is open. Log in to Facebook and solve any captchas\n"
            "(Ricardo / tutti) you see, then come back here and press Enter... "
        )


def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:80]
