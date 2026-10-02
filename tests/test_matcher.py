import pytest

from searchlight.matcher import Listing, Product, matches, parse_price
from searchlight.sources import build_sources


def listing(text):
    return Listing("tutti", "1", "https://example.com/1", text)


@pytest.mark.parametrize("text,expected", [
    ("MacBook Pro\nCHF 1'250.-", 1250),
    ("1'250.– CHF", 1250),
    ("Fr. 899.00", 899),
    ("CHF 1.299,50", 1299.5),
    ("1,299 CHF", 1299),
    ("MacBook Pro 14 M3\n1'450.00\nSofort kaufen", 1450),
    ("Zürich, 8004\n1'300.-", 1300),
    ("CHF1,350", 1350),
    ("Preis auf Anfrage", None),
    ("Version 2.4, 16GB", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_matches_any_phrase_in_any_order():
    p = Product("Laptop", keywords=["macbook pro m3 14"])
    assert matches(p, listing("Apple MacBook Pro 14\" (M3, 2023) space black\nCHF 1500"))
    assert not matches(p, listing("Apple MacBook Air M2\nCHF 900"))


def test_model_numbers_match_inside_longer_tokens():
    p = Product("Camera", keywords=["ilce 7m4"])
    assert matches(p, listing("Sony ILCE-7M4 body"))


def test_exclude_and_price_bounds():
    p = Product("Laptop", keywords=["macbook pro"], exclude=["hülle"], min_price=300, max_price=3000)
    assert not matches(p, listing("Hülle für MacBook Pro\nCHF 20"))
    assert not matches(p, listing("MacBook Pro sleeve\nCHF 25"))
    assert not matches(p, listing("MacBook Pro brand new\nCHF 4500"))
    assert matches(p, listing("MacBook Pro\nCHF 1200"))
    assert matches(p, listing("MacBook Pro\nPreis auf Anfrage"))  # unknown price isn't excluded


def test_accents_are_ignored():
    p = Product("Laptop", keywords=["hulle"])
    assert matches(p, listing("Hülle"))


def test_queries_default_to_keywords():
    assert Product("x", keywords=["a b"]).queries == ["a b"]


def test_source_overrides_and_custom_sources():
    srcs = build_sources(
        ["ricardo", "kleinanzeigen"],
        {
            "ricardo": {"search_url": "https://www.ricardo.ch/fr/s/{query_path}"},
            "kleinanzeigen": {
                "search_url": "https://k.de/s-{query_path}/k0",
                "link_pattern": r"/s-anzeige/[^/]+/(\d+)",
                "base_url": "https://k.de",
            },
        },
    )
    assert srcs[0].url_for("sony a7 iv") == "https://www.ricardo.ch/fr/s/sony%20a7%20iv"
    assert srcs[1].url_for("x") == "https://k.de/s-x/k0"
    with pytest.raises(ValueError):
        build_sources(["nope"], {})
