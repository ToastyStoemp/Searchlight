"""Searchlight: watch Swiss marketplaces for your stolen gear.

    python -m searchlight login          # one-off: log in to Facebook, solve captchas
    python -m searchlight once           # run every search one time
    python -m searchlight watch          # keep running every `interval_minutes`
    python -m searchlight report         # write evidence report (HTML) of all matches
    python -m searchlight test-notify    # send a test alert to your phone
"""

from __future__ import annotations

import argparse
import html
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import Config, load_config
from .matcher import Listing, matches
from .notify import Notifier
from .scraper import Blocked, Browser, safe_filename
from .store import Store

log = logging.getLogger("searchlight")


def run_once(cfg: Config, store: Store, notifier: Notifier, browser: Browser) -> int:
    found = 0
    for source in cfg.sources:
        searches = [(p, q) for p in cfg.products for q in p.queries]
        for product, query in searches:
            try:
                listings = browser.search(source, query, cfg.facebook_location)
            except Blocked as exc:
                log.error("%s", exc)
                break  # no point trying more queries on a blocked site
            except Exception as exc:
                log.error("[%s] search for %r failed: %s", source.name, query, exc)
                continue
            for listing in listings:
                store.mark_seen(listing)
                if matches(product, listing) and store.add_match(product.name, listing):
                    found += 1
                    if cfg.screenshot_matches:
                        shot = cfg.evidence_dir / (
                            f"{datetime.now():%Y%m%d-%H%M%S}_{listing.source}_"
                            f"{safe_filename(listing.listing_id)}.png"
                        )
                        if browser.screenshot(listing.url, shot):
                            store.set_screenshot(listing, str(shot))
                    notifier.send(product.name, listing)
    log.info("Run finished: %d new match(es)", found)
    return found


def write_report(cfg: Config, store: Store, out: Path) -> Path:
    rows = []
    for m in store.all_matches():
        price = f"CHF {m['price']:,.0f}".replace(",", "'") if m["price"] else ""
        shot = (
            f'<a href="{html.escape(Path(m["screenshot"]).as_uri())}">screenshot</a>'
            if m["screenshot"] else ""
        )
        img = f'<img src="{html.escape(m["image"])}" loading="lazy">' if m["image"] else ""
        rows.append(
            "<tr>"
            f"<td>{img}</td>"
            f"<td><b>{html.escape(m['product'])}</b><br>{html.escape(m['source'])}</td>"
            f"<td><a href=\"{html.escape(m['url'])}\">{html.escape(m['title'])}</a>"
            f"<pre>{html.escape(m['text'] or '')}</pre></td>"
            f"<td>{price}</td><td>{html.escape(m['found_at'])}</td><td>{shot}</td>"
            "</tr>"
        )
    out.write_text(
        f"""<!doctype html><meta charset="utf-8"><title>Searchlight matches</title>
<style>
body{{font:14px system-ui,sans-serif;margin:16px;background:#fff;color:#111}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:8px;vertical-align:top;text-align:left}}
img{{width:120px;border-radius:4px}}pre{{white-space:pre-wrap;color:#555;font:12px ui-monospace,monospace;margin:4px 0 0}}
</style>
<h1>Searchlight matches</h1>
<p>Generated {datetime.now():%Y-%m-%d %H:%M}. {len(rows)} match(es).</p>
<table><tr><th></th><th>Item / site</th><th>Listing</th><th>Price</th><th>Found</th><th>Evidence</th></tr>
{''.join(rows)}</table>""",
        encoding="utf-8",
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="searchlight", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["login", "once", "watch", "report", "test-notify"])
    parser.add_argument("-c", "--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    if not args.config.exists():
        log.error("No config at %s. Copy config.example.yaml to config.yaml and edit it.", args.config)
        return 1
    cfg = load_config(args.config)
    store = Store(cfg.db_path)
    notifier = Notifier(cfg.notify)

    if args.command == "test-notify":
        notifier.send("Test item", Listing("searchlight", "0", "https://ntfy.sh",
                                           "Searchlight test notification\nCHF 1"))
        return 0

    if args.command == "report":
        out = write_report(cfg, store, cfg.data_dir / "matches.html")
        print(f"Report written to {out}")
        return 0

    if args.command == "login":
        with Browser(cfg.profile_dir, headless=False) as browser:
            browser.open_for_login([
                s.url_for(cfg.products[0].queries[0], cfg.facebook_location) for s in cfg.sources
            ])
        return 0

    with Browser(cfg.profile_dir, headless=cfg.headless) as browser:
        if args.command == "once":
            run_once(cfg, store, notifier, browser)
            return 0
        while True:
            run_once(cfg, store, notifier, browser)
            # Jitter so requests don't arrive on an exact, bot-like schedule.
            wait = cfg.interval_minutes * 60 * random.uniform(0.8, 1.2)
            log.info("Next check in %.0f minutes", wait / 60)
            time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
