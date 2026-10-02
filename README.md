# Searchlight

Searchlight watches Swiss second-hand marketplaces for your stolen gear. It checks **Ricardo, tutti.ch, anibis.ch and Facebook Marketplace** every ~20 minutes. When a new listing matches one of your items, it sends a push to your phone and saves a full-page screenshot as evidence.

It runs on your own computer in a real Chrome window. Ricardo, tutti and Facebook all block requests from servers and from plain scripts, and Facebook Marketplace only shows results when you're logged in.

## Setup (about 5 minutes)

You need Python 3.10 or newer.

```bash
git clone <this repo> && cd Searchlight
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

cp config.example.yaml config.yaml   # then edit it: your items + ntfy topic
```

1. **Phone alerts:** install the free [ntfy](https://ntfy.sh) app (iOS/Android). Subscribe to a long random topic name and put that same name under `notify.ntfy.topic`. Check it works with `python -m searchlight test-notify`.
2. **Log in once:** `python -m searchlight login` opens a browser. Log in to Facebook and solve any captcha Ricardo or tutti shows, then press Enter. The browser profile is kept in `~/.searchlight/browser-profile`, so this lasts.
3. **Run:** `python -m searchlight watch`. Leave it running. `once` does a single pass.
4. **Evidence:** `python -m searchlight report` writes `~/.searchlight/matches.html`. It lists every match with the listing text, price, when it was found and a link to its screenshot.

Run it on a computer that stays on, such as an old laptop, a Mac mini or a Raspberry Pi with a desktop. A home internet connection gets far fewer captchas than a cloud server.

## Describing your items

```yaml
products:
  - name: Camera (Sony A7 IV)
    keywords: [sony a7 iv, sony a7iv, ilce 7m4]   # any one phrase; all its words must appear
    queries:  [sony a7 iv, a7iv]                  # what gets typed into each site's search
    exclude:  [akku, cage, gesucht]               # skip accessories and "wanted" ads
    min_price: 400
```

- Use the exact model, size, colour and year. Thieves often list things vaguely ("Laptop Apple 14 Zoll"), so add a broader query too and use `exclude` and `min_price` to cut the noise.
- Searchlight alerts on matches that are **already listed** when you first start it, not only new ones, in case your item went up straight after the theft.
- If a site changes its URLs, or you want to add another site (Kleinanzeigen, eBay, Marktplaats...), override it under `sources:` in the config. No code changes are needed. There's an example at the bottom of `config.example.yaml`.

## Use the sites' own alerts too

They're free and they cover listings even while your computer is off:

| Site | Built-in alert |
|---|---|
| Ricardo | Search, then **"Suche speichern"**. You get e-mail or app notifications for new items. |
| tutti.ch / anibis.ch | Search, then **"Suchabo"** (save search). It pushes new matches in the app. |
| Facebook Marketplace | Search in the app, then the **bell / "Benachrichtigungen"** toggle at the top of the results. |

Searchlight puts all sites in one place and adds price and keyword filtering on top. It also keeps the screenshot evidence, which matters because listings are often deleted quickly.

## If you find your item

- **Don't confront the seller or arrange a meeting yourself.** Send the police the link, the screenshot and the serial number.
- File a police report if you haven't (in Switzerland: any Kantonspolizei post or online at [suisse-epolice.ch](https://www.suisse-epolice.ch)). Include the **serial numbers**. For a Mac, they're on the original box or invoice, or at [appleid.apple.com](https://appleid.apple.com) under Devices. For a camera, check the box, the invoice or old photos' EXIF data (many cameras record the body serial).
- Report the listing to the marketplace as stolen goods.
- For a laptop: mark it lost in Find My / Find My Device, which also shows when it comes online.
- For a camera: register the serial on [stolencamerafinder.com](https://www.stolencamerafinder.com) / [lenstag.com](https://lenstag.com). They match photos posted online against the camera serial stored in the EXIF data.

## How it works

`searchlight/sources.py` defines each site as a search URL and a regex for its listing links. The scraper (`scraper.py`) loads the results page in Chromium and finds every link that matches. It then takes the surrounding card's text (title, price, location) and image. `matcher.py` decides whether a card matches one of your items. Every listing is recorded in SQLite (`~/.searchlight/searchlight.db`), so you get one alert per listing. Alerts go out through ntfy, Telegram or e-mail (`notify.py`).

Tests: `pip install pytest && pytest`.

Please keep the check interval sensible (the default is 20 minutes). It's your own personal search, done at human speed.
