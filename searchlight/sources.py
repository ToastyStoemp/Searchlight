"""Built-in marketplace definitions.

Each source is described by data only: a search URL template (sorted by newest
where the site supports it) and a regex that recognises listing links and
captures the listing id. Sites change their URLs from time to time; when that
happens you can override any of these from the `sources:` section of your
config without touching the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote, quote_plus


@dataclass
class Source:
    name: str
    search_url: str
    link_pattern: str
    base_url: str
    needs_login: bool = False
    # Text that only appears on a bot-check / captcha page.
    block_markers: list[str] = field(default_factory=list)

    def url_for(self, query: str, location: str = "") -> str:
        return self.search_url.format(
            query=quote_plus(query),
            query_path=quote(query),
            location=location,
        )


BUILTIN_SOURCES: dict[str, Source] = {
    "ricardo": Source(
        name="ricardo",
        search_url="https://www.ricardo.ch/de/s/{query_path}?sort=newest",
        link_pattern=r"/(?:de|fr|it|en)/a/[^/?#]*?-(\d{6,})/?",
        base_url="https://www.ricardo.ch",
        block_markers=["Ricardo Captcha"],
    ),
    "tutti": Source(
        name="tutti",
        search_url="https://www.tutti.ch/de/q/suche?query={query}&sorting=newest",
        link_pattern=r"/(?:de|fr|it)/vi/(?:[^/?#]+/)+(\d{6,})",
        base_url="https://www.tutti.ch",
        block_markers=["tutti.ch - Error"],
    ),
    "anibis": Source(
        name="anibis",
        search_url="https://www.anibis.ch/de/q/suche?query={query}&sorting=newest",
        link_pattern=r"/(?:de|fr|it)/vi/(?:[^/?#]+/)+(\d{6,})",
        base_url="https://www.anibis.ch",
    ),
    "facebook": Source(
        name="facebook",
        search_url=(
            "https://www.facebook.com/marketplace/{location}/search"
            "?query={query}&sortBy=creation_time_descend&exact=false"
        ),
        link_pattern=r"/marketplace/item/(\d+)",
        base_url="https://www.facebook.com",
        needs_login=True,
        block_markers=["Log in to Facebook", "Melde dich bei Facebook an"],
    ),
}


def build_sources(enabled: list[str], overrides: dict[str, dict]) -> list[Source]:
    """Return the enabled sources, applying any per-source overrides from config.

    An override for a name that isn't built in defines a brand-new source, so
    other marketplaces can be added from the config file alone.
    """
    result = []
    for name in enabled:
        override = overrides.get(name, {})
        base = BUILTIN_SOURCES.get(name)
        if base is None:
            missing = {"search_url", "link_pattern", "base_url"} - override.keys()
            if missing:
                raise ValueError(
                    f"Unknown source '{name}': define {', '.join(sorted(missing))} "
                    "for it under `sources:` in the config"
                )
            result.append(Source(name=name, **override))
        else:
            fields = {**base.__dict__, **override, "name": name}
            result.append(Source(**fields))
    return result
