"""Load search pages in a real browser and pull listing cards out of them.

A real (persistent) Chromium profile is used rather than plain HTTP requests
because Ricardo, tutti and Facebook all sit behind bot protection, and
Facebook Marketplace needs you to be logged in. Captchas you solve and logins
you make in `searchlight login` are remembered in that profile.

On a machine without a screen the browser runs headless. Log in to Facebook
on a computer with a screen (`searchlight login`), then copy the session file
it writes to the server.

When a site answers with a captcha, Searchlight doesn't try to get past it: if
a browser window is visible it asks you to solve it there, otherwise it skips
that site for a while and tells you.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from collections.abc import Callable
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


CAPTCHA_FRAME_HINTS = (
    "captcha", "challenges.cloudflare.com", "datadome", "geo.captcha-delivery",
    "perimeterx", "px-cdn", "arkoselabs", "funcaptcha",
)
COOKIE_BUTTONS = re.compile(
    r"^\s*(alle (cookies )?(akzeptieren|erlauben|zulassen)|accept all( cookies)?|allow all cookies"
    r"|tout accepter|accetta tutti|akzeptieren|einverstanden|ich stimme zu)\s*$",
    re.IGNORECASE,
)


def extract_listings(page: Page, source: Source) -> list[Listing]:
    raw = page.evaluate(EXTRACT_JS, source.link_pattern)
    listings = []
    for item in raw:
        url = urljoin(source.base_url, item["href"]).split("?")[0]
        listings.append(Listing(source.name, item["id"], url, item["text"], item["image"]))
    return listings


class Browser:
    def __init__(
        self,
        profile_dir: Path,
        headless: bool,
        slow: bool = True,
        session_file: Path | None = None,
        captcha_wait_minutes: float = 0,
        on_captcha: Callable[[Source, str], None] | None = None,
    ):
        self.profile_dir = profile_dir
        self.headless = headless
        self.slow = slow
        self.session_file = session_file
        self.captcha_wait_minutes = captcha_wait_minutes
        self.on_captcha = on_captcha
        self._pw = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "Browser":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        try:
            self._launch()
        except BaseException:
            self._pw.stop()  # __exit__ won't run if __enter__ fails
            raise
        return self

    def _launch(self) -> None:
        executable = os.environ.get("SEARCHLIGHT_CHROMIUM") or None
        self.context = self._pw.chromium.launch_persistent_context(
            str(self.profile_dir),
            headless=self.headless,
            executable_path=executable,
            locale="de-CH",
            timezone_id="Europe/Zurich",
            viewport={"width": 1366, "height": 900},
        )
        if self.session_file and self.session_file.exists():
            state = json.loads(self.session_file.read_text(encoding="utf-8"))
            self.context.add_cookies(state.get("cookies", []))
            log.info("Loaded saved login session from %s", self.session_file)

    def save_session(self, path: Path) -> None:
        """Write the cookies (Facebook login etc.) so another machine can use them."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.context.storage_state(path=str(path))
        try:
            path.chmod(0o600)  # it's as good as your password
        except OSError:
            pass

    def __exit__(self, *exc):
        if self.context:
            self.context.close()
        if self._pw:
            self._pw.stop()

    def _pause(self, page: Page, lo: float, hi: float) -> None:
        if self.slow:
            page.wait_for_timeout(random.uniform(lo, hi) * 1000)

    def _settle(self, page: Page) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass  # some sites never go idle; what's loaded is enough

    def _scroll(self, page: Page, times: int = 3) -> None:
        """Scroll down so lazily rendered cards (Facebook) and photos load."""
        for _ in range(times):
            page.mouse.wheel(0, 2500)
            self._pause(page, 0.8, 1.6)

    def _accept_cookies(self, page: Page) -> None:
        try:
            buttons = page.get_by_role("button", name=COOKIE_BUTTONS)
            if buttons.count():
                buttons.first.click(timeout=3_000)
                self._pause(page, 0.5, 1.2)
        except Exception:
            pass

    def _looks_blocked(self, page: Page, source: Source) -> bool:
        try:
            title = page.title()
            body = page.content()
        except Exception:
            return False
        if any(m in title or m in body for m in source.block_markers):
            return True
        if "captcha" in title.lower():
            return True
        return any(any(h in (f.url or "").lower() for h in CAPTCHA_FRAME_HINTS)
                   for f in page.frames[1:])

    def _wait_for_human(self, page: Page, source: Source) -> list[Listing]:
        """Leave the captcha on screen for the user to solve; return the
        listings as soon as the page shows results again."""
        if self.on_captcha:
            self.on_captcha(source, page.url)
        page.bring_to_front()
        log.warning("[%s] Waiting up to %.0f min for the captcha to be solved in the browser window",
                    source.name, self.captcha_wait_minutes)
        deadline = time.monotonic() + self.captcha_wait_minutes * 60
        while time.monotonic() < deadline:
            page.wait_for_timeout(5_000)
            try:
                listings = extract_listings(page, source)
            except Exception:
                continue  # page is navigating after the solve
            if listings:
                log.info("[%s] Captcha solved, carrying on", source.name)
                return listings
        return []

    def search(self, source: Source, query: str, location: str = "") -> list[Listing]:
        url = source.url_for(query, location)
        page = self.context.new_page()
        try:
            log.info("[%s] %s", source.name, url)
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            self._settle(page)
            self._accept_cookies(page)
            self._pause(page, 1.5, 3.5)
            self._scroll(page)
            listings = extract_listings(page, source)

            if not listings and self._looks_blocked(page, source):
                if not self.headless and self.captcha_wait_minutes > 0:
                    listings = self._wait_for_human(page, source)
                if not listings:
                    raise Blocked(f"{source.name} is showing a captcha or login page")

            log.info("[%s] %d listings for %r", source.name, len(listings), query)
            return listings
        finally:
            page.close()

    def backup(self, listing: Listing, folder: Path) -> dict[str, str]:
        """Save everything needed to see the listing after it's taken down.

        Writes, into `folder`:
          page.mhtml      the whole page in one file, opens offline in Chrome/Edge
          page.html       raw HTML
          screenshot.png  full-page screenshot
          listing.json    the search-result card, URL and capture time
          images/         every listing photo at full size
        Returns the paths that were written, keyed by kind.
        """
        folder.mkdir(parents=True, exist_ok=True)
        saved: dict[str, str] = {}

        # The search-result card is saved first: it's already in hand, so it
        # survives even if the listing page itself won't load.
        meta = {
            "source": listing.source, "listing_id": listing.listing_id, "url": listing.url,
            "title": listing.title, "price": listing.price, "card_text": listing.text,
            "card_image": listing.image,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        image_urls = [listing.image] if listing.image else []

        page = self.context.new_page()
        try:
            page.goto(listing.url, wait_until="domcontentloaded", timeout=45_000)
            self._settle(page)
            self._accept_cookies(page)
            self._expand_description(page)
            self._scroll(page, 2)
            page.evaluate("window.scrollTo(0, 0)")
            self._pause(page, 1, 2)

            meta["final_url"] = page.url
            meta["page_title"] = page.title()
            meta["page_text"] = page.inner_text("body")
            if self._looks_blocked(page, Source(listing.source, "", "", "")):
                meta["warning"] = "The listing page showed a captcha/login wall; only the card was saved."

            page.screenshot(path=str(folder / "screenshot.png"), full_page=True)
            saved["screenshot"] = str(folder / "screenshot.png")
            (folder / "page.html").write_text(page.content(), encoding="utf-8")
            saved["html"] = str(folder / "page.html")
            try:
                cdp = self.context.new_cdp_session(page)
                snap = cdp.send("Page.captureSnapshot", {"format": "mhtml"})
                (folder / "page.mhtml").write_text(snap["data"], encoding="utf-8")
                saved["mhtml"] = str(folder / "page.mhtml")
            except Exception as exc:
                log.debug("MHTML snapshot failed: %s", exc)

            image_urls += page.evaluate(
                """() => [...document.images]
                     .filter(i => i.naturalWidth >= 250 && i.naturalHeight >= 250)
                     .map(i => i.currentSrc || i.src)"""
            )
        except Exception as exc:
            log.error("Backup of %s was incomplete: %s", listing.url, exc)
            meta["error"] = str(exc)
        finally:
            page.close()

        saved_images = self._download_images(image_urls, folder / "images", listing.url)
        if saved_images:
            saved["images"] = str(folder / "images")
        meta["images"] = saved_images
        (folder / "listing.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        saved["json"] = str(folder / "listing.json")
        return saved

    def _expand_description(self, page: Page) -> None:
        for label in ("Mehr anzeigen", "See more", "Weiterlesen", "Voir plus"):
            try:
                more = page.get_by_role("button", name=label, exact=True)
                if more.count():
                    more.first.click(timeout=2_000)
                    self._pause(page, 0.4, 0.9)
            except Exception:
                pass

    def _download_images(self, urls: list[str], folder: Path, referer: str) -> list[str]:
        names = []
        seen = set()
        for url in urls:
            if not url or url.startswith("data:") or url in seen:
                continue
            seen.add(url)
            try:
                resp = self.context.request.get(url, headers={"Referer": referer}, timeout=30_000)
                if not resp.ok:
                    continue
                kind = (resp.headers.get("content-type") or "").split("/")[-1].split(";")[0]
                ext = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif", "avif": ".avif"}.get(kind)
                if not ext:
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                name = f"{len(names) + 1:02d}{ext}"
                (folder / name).write_bytes(resp.body())
                names.append(name)
            except Exception as exc:
                log.debug("Image %s not saved: %s", url, exc)
        return names

    def open_for_login(self, urls: list[str]) -> None:
        for url in urls:
            self.context.new_page().goto(url)
        input(
            "\nA browser window is open. Log in to Facebook (and accept cookie banners),\n"
            "then come back here and press Enter... "
        )


def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:80]
