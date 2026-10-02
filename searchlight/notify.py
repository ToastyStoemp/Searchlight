"""Send alerts for new matches: ntfy (phone push), Telegram, e-mail."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import requests

from .matcher import Listing

log = logging.getLogger(__name__)


def _message(product: str, listing: Listing) -> tuple[str, str]:
    price = f"CHF {listing.price:,.0f}".replace(",", "'") if listing.price else "price n/a"
    title = f"Possible match for {product} on {listing.source}"
    body = f"{listing.title}\n{price}\n{listing.url}"
    return title, body


class Notifier:
    def __init__(self, config: dict):
        self.config = config or {}

    def send(self, product: str, listing: Listing) -> None:
        title, body = _message(product, listing)
        log.warning("MATCH  %s | %s", title, body.replace("\n", " | "))
        for name, fn in (("ntfy", self._ntfy), ("telegram", self._telegram), ("email", self._email)):
            cfg = self.config.get(name)
            if not cfg:
                continue
            try:
                fn(cfg, title, body, listing)
            except Exception as exc:  # one broken channel shouldn't stop the others
                log.error("Could not send %s notification: %s", name, exc)

    def _ntfy(self, cfg, title, body, listing):
        server = cfg.get("server", "https://ntfy.sh").rstrip("/")
        headers = {
            "Title": title.encode("utf-8"),
            "Click": listing.url,
            "Tags": "rotating_light",
            "Priority": str(cfg.get("priority", "high")),
        }
        if listing.image:
            headers["Attach"] = listing.image
        if cfg.get("token"):
            headers["Authorization"] = f"Bearer {cfg['token']}"
        requests.post(f"{server}/{cfg['topic']}", data=body.encode("utf-8"),
                      headers=headers, timeout=20).raise_for_status()

    def _telegram(self, cfg, title, body, listing):
        requests.post(
            f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
            json={"chat_id": cfg["chat_id"], "text": f"{title}\n\n{body}"},
            timeout=20,
        ).raise_for_status()

    def _email(self, cfg, title, body, listing):
        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = cfg.get("from", cfg["username"])
        msg["To"] = cfg["to"]
        msg.set_content(body)
        with smtplib.SMTP(cfg.get("host", "smtp.gmail.com"), int(cfg.get("port", 587)), timeout=30) as s:
            s.starttls()
            s.login(cfg["username"], cfg["password"])
            s.send_message(msg)
