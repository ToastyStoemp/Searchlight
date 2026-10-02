# Searchlight

Searchlight watches Swiss second-hand marketplaces for your stolen gear. It checks **Ricardo, tutti.ch, anibis.ch and Facebook Marketplace** every ~90 minutes during the day. When a listing matches one of your items, it sends a push to your phone and **saves a complete offline copy of the listing**, so you still have it if the seller takes it down.

It drives a real Chromium browser, either visible on your desktop or invisible (headless) on a server. Facebook Marketplace only shows results when you're logged in, so you log in once on a computer with a screen and copy the session to the server.

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
2. **Log in to Facebook once:** `python -m searchlight login` opens a browser. Log in, accept the cookie banners, then press Enter. This writes `~/.searchlight/session.json` (skip this step if you don't want Facebook).
3. **Run:** `python -m searchlight watch`. Leave it running. `once` does a single pass.
4. **Evidence:** `python -m searchlight report` writes `~/.searchlight/matches.html`, listing every match with links to its backup.

## Running it on a Mac mini (recommended)

A Mac at home is the best place for Searchlight. A home connection gets far fewer captchas than a cloud server. The Mac also has a real screen session, so the browser window is visible and you can log in to Facebook directly on it.

```bash
git clone <this repo> && cd Searchlight
./scripts/install-macos.sh          # first run creates config.yaml: edit it, then run again
./scripts/install-macos.sh login    # log in to Facebook in the window that opens, press Enter
```

The script installs everything into `.venv` and registers a background service that:
- starts when you log in
- restarts if it crashes
- keeps the Mac awake while it runs

The log is at `~/.searchlight/searchlight.log`. `./scripts/install-macos.sh uninstall` removes the service and keeps your data.

Mac settings worth changing once (System Settings):
- **General → Sharing → Screen Sharing: on.** When a captcha alert arrives, connect from another Mac (Finder → Network, or `vnc://<mac-mini-name>.local`) or from your phone (any VNC app, e.g. RealVNC Viewer). Solve it in the Searchlight window within 10 minutes.
- **Energy → "Start up automatically after a power failure": on.** On some macOS versions, also turn on "Prevent automatic sleeping when the display is off".
- **Users & Groups → Automatically log in as: your user.** The service runs in your login session, so it only starts again after a reboot if the Mac logs itself in. macOS hides this option while FileVault is on. Without it, you need to log in once after a restart.

## Running it on a server

A Linux box or NAS works too, though a cloud server will likely get blocked (see below). Do steps 1 and 2 on your laptop. Then, on the server:

```bash
git clone <this repo> && cd Searchlight
mkdir data
cp config.example.yaml data/config.yaml     # edit it, and set: data_dir: /data
scp laptop:~/.searchlight/session.json data/ # only if you use Facebook
docker compose up -d --build                 # runs `watch` and restarts on reboot
docker compose logs -f                       # see what it's doing
docker compose run --rm searchlight report   # writes data/matches.html
```

Without Docker, the steps from **Setup** work on a server too: install with `playwright install --with-deps chromium`. `headless: auto` notices there's no screen.

- **Where the server is matters most.** Ricardo and tutti block many rented cloud servers (AWS, Hetzner, DigitalOcean...) outright, before any captcha. A computer at home works much better: a Raspberry Pi, a NAS that runs Docker, or an old laptop. If you do use a cloud server and a site keeps getting blocked, take that site out of `enabled_sources` there and rely on its built-in alert (below).
- **The Facebook session lasts weeks, not forever.** Facebook may also ask you to confirm the "new device" the first time the server uses it. Approve it in the Facebook app. When Facebook starts showing the login page, you'll get a push. Then run `login` on your laptop again and copy the new `session.json`. Treat that file like a password.

## When a site shows a captcha

Searchlight doesn't try to trick or solve captchas. To avoid them, it checks politely: every ~90 minutes, only between 07:00 and 23:00, with a random 20-75 s pause between searches.

If a site still shows a captcha or login page:
- **On a desktop** (visible window): you get a push. Solve it in the window within 10 minutes and the search carries on.
- **On a server:** the site is skipped for 2 hours, then 4, 8... up to 24 hours. You get a push each time it's blocked, and the other sites keep being checked. The pause resets as soon as a search on that site works again.

All of this can be tuned in `config.yaml` (`interval_minutes`, `active_hours`, `search_delay_seconds`, `captcha_wait_minutes`, `block_cooldown_hours`).

## Backups of matching listings

For every match, Searchlight opens the listing and saves a folder under `~/.searchlight/backups/`:

| File | What it is |
|---|---|
| `page.mhtml` | The whole page, photos included, in one file. Opens offline in Chrome or Edge, even after the listing is deleted. |
| `screenshot.png` | Full-page screenshot. |
| `images/` | Every listing photo at full size. |
| `listing.json` | Title, price, the full page text (including the seller name and location when shown), the URL and the exact capture time. |
| `page.html` | The raw HTML. |

The card from the search results is saved first. If the listing page itself can't be loaded (a captcha, or it's already gone), you still keep the title, price, text and thumbnail.

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

Searchlight puts all sites in one place and adds price and keyword filtering on top. It also keeps backups of matches, which matters because listings are often deleted quickly.

## If you find your item

- **Don't confront the seller or arrange a meeting yourself.** Send the police the link, the backup folder and the serial number.
- File a police report if you haven't (in Switzerland: any Kantonspolizei post or online at [suisse-epolice.ch](https://www.suisse-epolice.ch)). Include the **serial numbers**. For a Mac, they're on the original box or invoice, or at [appleid.apple.com](https://appleid.apple.com) under Devices. For a camera, check the box, the invoice or old photos' EXIF data (many cameras record the body serial).
- Report the listing to the marketplace as stolen goods.
- For a laptop: mark it lost in Find My / Find My Device, which also shows when it comes online.
- For a camera: register the serial on [stolencamerafinder.com](https://www.stolencamerafinder.com) / [lenstag.com](https://lenstag.com). They match photos posted online against the camera serial stored in the EXIF data.

## How it works

`searchlight/sources.py` defines each site as a search URL and a regex for its listing links. The scraper (`scraper.py`) loads the results page in Chromium and finds every link that matches. It then takes the surrounding card's text (title, price, location) and image. `matcher.py` decides whether a card matches one of your items. Every listing is recorded in SQLite (`~/.searchlight/searchlight.db`), so you get one alert per listing. Alerts go out through ntfy, Telegram or e-mail (`notify.py`).

Tests: `pip install pytest && pytest`.

Please keep the check interval sensible. It's your own personal search, done at human speed.
