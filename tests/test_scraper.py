"""Run the real extraction JS in Chromium against small offline pages that
mimic each site's result markup."""

import os

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from searchlight.matcher import Product, matches  # noqa: E402
from searchlight.scraper import extract_listings  # noqa: E402
from searchlight.sources import BUILTIN_SOURCES  # noqa: E402

PAGES = {
    "ricardo": """
      <div class="grid">
        <a href="/de/a/macbook-pro-14-m3-space-black-1287654321/">
          <img src="https://img.ricardo.ch/1.jpg">
          <p>MacBook Pro 14 M3 Space Black 1TB</p><span>1'450.00</span><span>Sofort kaufen</span>
        </a>
        <a href="/de/a/sony-a7-iv-gehause-1287654322/"><p>Sony A7 IV Gehäuse</p><span>CHF 1'600.00</span></a>
        <a href="/de/s/macbook">not a listing</a>
      </div>""",
    "tutti": """
      <div>
        <div class="card"><a href="/de/vi/zuerich/computer-zubehoer/notebooks/58123456">
          <img src="https://c.tutti.ch/a.jpg"></a>
          <div><a href="/de/vi/zuerich/computer-zubehoer/notebooks/58123456">MacBook Pro M3 14 Zoll</a></div>
          <span>Zürich, 8004</span><span>1'300.-</span></div>
        <div class="card"><a href="/de/vi/bern/foto/kameras/58123457">Kamera Sony a7iv mit 24-70</a>
          <span>CHF 1'900.-</span></div>
      </div>""",
    "facebook": """
      <div role="main"><div>
        <div><a href="/marketplace/item/912345678901234/?ref=search">
          <img src="https://scontent.xx/1.jpg"><span>CHF1,350</span>
          <span>MacBook Pro 14 M3</span><span>Zürich, ZH</span></a></div>
        <div><a href="/marketplace/item/912345678901235/"><span>CHF80</span><span>MacBook charger</span></a></div>
      </div></div>""",
}


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as pw:
        # PW_CHROMIUM lets CI use a pre-installed browser of another version.
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        yield browser.new_page()
        browser.close()


@pytest.mark.parametrize("site", PAGES)
def test_extracts_cards(page, site):
    source = BUILTIN_SOURCES[site]
    page.set_content(f"<html><body>{PAGES[site]}</body></html>")
    listings = extract_listings(page, source)
    assert len(listings) == 2
    first = listings[0]
    assert first.url.startswith(source.base_url)
    assert "?" not in first.url
    assert "MacBook Pro" in first.title
    assert first.price and 1200 < first.price < 1500

    laptop = Product("Laptop", keywords=["macbook pro m3"], min_price=300)
    assert [matches(laptop, l) for l in listings] == [True, False]


def test_tutti_card_merges_image_and_text_links(page):
    page.set_content(f"<html><body>{PAGES['tutti']}</body></html>")
    first = extract_listings(page, BUILTIN_SOURCES["tutti"])[0]
    assert first.listing_id == "58123456"
    assert first.image == "https://c.tutti.ch/a.jpg"
    assert "Zürich" in first.text

