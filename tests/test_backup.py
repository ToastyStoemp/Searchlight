"""Backup of a matched listing, against a local web server.

Kept apart from test_scraper.py: Playwright's sync API can't run two sessions
at once, and that module holds one open for its whole run."""

import pytest

pytest.importorskip("playwright")


def test_backup_saves_page_screenshot_and_photos(tmp_path):
    import base64
    import http.server
    import json
    import threading

    from searchlight.matcher import Listing
    from searchlight.scraper import Browser

    site = tmp_path / "site"
    site.mkdir()
    # 300x300 PNG so it counts as a listing photo, not an icon.
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAASwAAAEsAQMAAABDsxw2AAAAA1BMVEX/AAAZ4gk3AAAAIklEQVR4Xu3AMQEAAADCoPVPbQ0PoAAAAAAAAAAAAAAA4N8AKvgAAUFvXqMAAAAASUVORK5CYII=")
    (site / "photo.png").write_bytes(png)
    (site / "item.html").write_text(
        "<html><title>MacBook Pro M3</title><body><h1>MacBook Pro 14 M3</h1>"
        "<p>Seriennummer abgekratzt, CHF 900</p><img src='photo.png' width=300 height=300></body></html>")

    handler = lambda *a: http.server.SimpleHTTPRequestHandler(*a, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/item.html"
    try:
        listing = Listing("test", "42", url, "MacBook Pro 14 M3\nCHF 900")
        with Browser(tmp_path / "profile", headless=True, slow=False) as browser:
            saved = browser.backup(listing, tmp_path / "backup")
    finally:
        server.shutdown()

    folder = tmp_path / "backup"
    assert {"screenshot", "html", "mhtml", "images", "json"} <= saved.keys()
    # MHTML is a MIME archive; decode it to check the page itself is inside.
    import email
    archive = email.message_from_string((folder / "page.mhtml").read_text())
    parts = {p.get_content_type(): p.get_payload(decode=True) for p in archive.walk()}
    assert b"MacBook Pro 14 M3" in parts["text/html"]
    assert parts["image/png"] == png  # photo embedded, so it opens offline
    assert (folder / "images" / "01.png").read_bytes() == png
    meta = json.loads((folder / "listing.json").read_text())
    assert meta["card_text"] == listing.text
    assert "Seriennummer abgekratzt" in meta["page_text"]
    assert meta["images"] == ["01.png"]
