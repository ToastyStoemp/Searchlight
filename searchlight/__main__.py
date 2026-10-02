"""Searchlight: watch Swiss marketplaces for your stolen gear.

    python -m searchlight login          # log in to Facebook; saves a session file
    python -m searchlight once           # run every search one time
    python -m searchlight watch          # keep running every `interval_minutes`
    python -m searchlight report         # write evidence report (HTML) of all matches
    python -m searchlight test-notify    # send a test alert to your phone
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config, has_display, load_config
from .matcher import Listing, matches
from .notify import Notifier
from .scraper import Blocked, Browser, safe_filename
from .store import Store

log = logging.getLogger("searchlight")


def run_once(cfg: Config, store: Store, notifier: Notifier, browser: Browser) -> int:
    found = 0
    sources = list(cfg.sources)
    random.shuffle(sources)
    first_search = True
    for source in sources:
        until = store.blocked_until(source.name)
        if until > time.time():
            log.info("[%s] skipped: blocked us recently, retrying after %s",
                     source.name, datetime.fromtimestamp(until).strftime("%a %H:%M"))
            continue

        searches = [(p, q) for p in cfg.products for q in p.queries]
        random.shuffle(searches)
        succeeded = False
        for product, query in searches:
            if not first_search:
                time.sleep(random.uniform(*cfg.search_delay_seconds))
            first_search = False
            try:
                listings = browser.search(source, query, cfg.facebook_location)
            except Blocked as exc:
                until = store.record_block(source.name, cfg.block_cooldown_hours)
                when = datetime.fromtimestamp(until).strftime("%a %H:%M")
                log.error("%s; leaving it alone until %s", exc, when)
                notifier.send_text(
                    f"Searchlight: {source.name} is blocking searches",
                    f"{exc}. Searchlight will try again after {when}. "
                    + ("If this keeps happening for Facebook, run `searchlight login` "
                       "again and copy the new session file." if source.needs_login else
                       "Other sites keep being checked meanwhile."),
                )
                break  # no point trying more queries on a blocked site
            except Exception as exc:
                log.error("[%s] search for %r failed: %s", source.name, query, exc)
                continue
            succeeded = True
            for listing in listings:
                store.mark_seen(listing)
                if matches(product, listing) and store.add_match(product.name, listing):
                    found += 1
                    if cfg.backup_matches:
                        backup(cfg, store, browser, listing)
                    notifier.send(product.name, listing)
        if succeeded:
            store.record_success(source.name)
    log.info("Run finished: %d new match(es)", found)
    return found


def backup(cfg: Config, store: Store, browser: Browser, listing: Listing) -> None:
    folder = cfg.backup_dir / (
        f"{datetime.now():%Y%m%d-%H%M%S}_{listing.source}_{safe_filename(listing.listing_id)}"
    )
    saved = browser.backup(listing, folder)
    store.set_backup(listing, str(folder), saved.get("screenshot"))
    log.info("Backed up listing to %s", folder)


def seconds_until_active(active_hours: tuple[int, int], now: datetime | None = None) -> float:
    """0 inside the active window, otherwise the wait until it next opens."""
    now = now or datetime.now()
    start, end = active_hours
    if start == end:
        return 0  # always active
    inside = start <= now.hour < end if start < end else (now.hour >= start or now.hour < end)
    if inside:
        return 0
    opens = now.replace(hour=start, minute=0, second=0, microsecond=0)
    if opens <= now:
        opens += timedelta(days=1)
    return (opens - now).total_seconds()


def write_report(cfg: Config, store: Store, out: Path) -> Path:
    def rel(path: str) -> str:
        p = Path(path)
        try:
            return html.escape(p.relative_to(out.parent).as_posix())
        except ValueError:
            return html.escape(p.as_uri())

    rows = []
    for m in store.all_matches():
        price = f"CHF {m['price']:,.0f}".replace(",", "'") if m["price"] else ""
        img = f'<img src="{html.escape(m["image"])}" loading="lazy">' if m["image"] else ""
        links = []
        folder = Path(m["backup_dir"]) if m["backup_dir"] else None
        if folder and folder.exists():
            meta_file = folder / "listing.json"
            meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
            if meta.get("images"):
                # Prefer the saved copy: the online photo disappears with the listing.
                img = f'<img src="{rel(str(folder / "images" / meta["images"][0]))}">'
            for name, label in (("page.mhtml", "offline page"), ("screenshot.png", "screenshot"),
                                ("images", "photos"), ("listing.json", "data")):
                if (folder / name).exists():
                    links.append(f'<a href="{rel(str(folder / name))}">{label}</a>')
            if meta.get("warning") or meta.get("error"):
                links.append(f"<small>{html.escape(meta.get('warning') or meta.get('error'))}</small>")
        elif m["screenshot"]:
            links.append(f'<a href="{rel(m["screenshot"])}">screenshot</a>')
        rows.append(
            "<tr>"
            f"<td>{img}</td>"
            f"<td><b>{html.escape(m['product'])}</b><br>{html.escape(m['source'])}</td>"
            f"<td><a href=\"{html.escape(m['url'])}\">{html.escape(m['title'])}</a>"
            f"<pre>{html.escape(m['text'] or '')}</pre></td>"
            f"<td>{price}</td><td>{html.escape(m['found_at'])}</td><td>{'<br>'.join(links)}</td>"
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
<p>Generated {datetime.now():%Y-%m-%d %H:%M}. {len(rows)} match(es).
"Offline page" opens in Chrome or Edge even after the listing is taken down.</p>
<table><tr><th></th><th>Item / site</th><th>Listing</th><th>Price</th><th>Found</th><th>Backup</th></tr>
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
        datefmt="%Y-%m-%d %H:%M:%S",
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
        if not has_display():
            log.error("`login` needs a screen. Run it on your laptop, then copy %s "
                      "to the same place on the server.", cfg.session_file)
            return 1
        with Browser(cfg.profile_dir, headless=False) as browser:
            browser.open_for_login([
                s.url_for(cfg.products[0].queries[0], cfg.facebook_location) for s in cfg.sources
            ])
            browser.save_session(cfg.session_file)
        print(f"\nSession saved to {cfg.session_file}\n"
              "To use it on a server, copy that file into the server's data_dir. "
              "Treat it like a password.")
        return 0

    def on_captcha(source, url):
        notifier.send_text(f"Searchlight: solve a captcha on {source.name}",
                           "A captcha is waiting in the Searchlight browser window.", url)

    with Browser(cfg.profile_dir, headless=cfg.headless, session_file=cfg.session_file,
                 captcha_wait_minutes=cfg.captcha_wait_minutes, on_captcha=on_captcha) as browser:
        if args.command == "once":
            run_once(cfg, store, notifier, browser)
            return 0
        while True:
            idle = seconds_until_active(cfg.active_hours)
            if idle:
                log.info("Outside active hours, sleeping %.1f h", idle / 3600)
                time.sleep(idle)
            run_once(cfg, store, notifier, browser)
            # Jitter so checks don't land on an exact schedule.
            wait = cfg.interval_minutes * 60 * random.uniform(0.8, 1.2)
            log.info("Next check in %.0f minutes", wait / 60)
            time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
