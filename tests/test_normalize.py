import pytest

from mtg_toolkits.normalize import (
    MAX_QUANTITY, SET_ALIAS_PREFIXES, normalize_collector_number, normalize_set_code, parse_number, parse_quantity,
    set_alias_map,
)


@pytest.mark.parametrize("text, expected", [
    ("1.50", 1.5), ("1,50", 1.5), ("$1.50", 1.5), ("€1.50", 1.5), ("1,50 €", 1.5), ("£ 2", 2.0),
    ("1,234.50", 1234.5), ("1.234,50", 1234.5), ("1,234", 1234.0), ("1,234,567", 1234567.0),
    ("1.234.567", 1234567.0), ("1 234,50", 1234.5), ("1.234", 1.234), ("1,5", 1.5), ("-2.5", -2.5),
    (".5", 0.5), ("", None), (None, None), ("  ", None), ("abc", None), ("1,2,3", None), ("1.2.3,4.5", None),
    ("inf", None), ("nan", None), ("1e309", None), ("1e3", None), ("1_000", None), ("9" * 400, None),
])
def test_parse_number(text, expected):
    assert parse_number(text) == expected


def test_parse_quantity():
    assert (parse_quantity("3"), parse_quantity("1.0"), parse_quantity("1,234"), parse_quantity(" 0 ")) == (3, 1, 1234, 0)
    assert parse_quantity("", default=1) == 1 and parse_quantity(None, default=0) == 0
    assert parse_quantity(str(MAX_QUANTITY)) == MAX_QUANTITY
    for bad in ("abc", "1.5", "-1", "inf", "nan", "1e30", "99999999999999999999999", str(MAX_QUANTITY + 1)):
        with pytest.raises(ValueError):
            parse_quantity(bad)


def test_normalize_set_code():
    from mtg_toolkits import dragonshield

    codes = [" NEO ", "Neo", "GK2_ORZHOV", "gk1_selesn", "GK2_FOO", "LEGI", "", None]
    expected = ["neo", "neo", "gk2", "gk1", "gk2", "leg", None, None]
    assert [normalize_set_code(c) for c in codes] == expected
    assert [dragonshield.scryfall_set_code(c) for c in codes] == expected


def test_set_alias_map_is_a_copy_callers_can_ship():
    aliases = set_alias_map()
    assert aliases["legi"] == "leg" and aliases["gk2_orzhov"] == "gk2"
    aliases["legi"] = "nope"
    assert set_alias_map()["legi"] == "leg"
    assert SET_ALIAS_PREFIXES == ("gk1_", "gk2_")


@pytest.mark.parametrize("number, expected", [
    ("007", "7"), ("123A", "123a"), ("1*", "1★"), (" 001★ ", "1★"), ("C15-56", "c15-56"), ("0", "0"), ("00", "0"),
    ("007a", "7a"), ("", None), (None, None),
])
def test_normalize_collector_number(number, expected):
    assert normalize_collector_number(number) == expected


def test_scryfall_identifier_is_normalised():
    from mtg_toolkits.models import CollectionEntry as E

    assert E("Orzhov Signet", set_code="GK2_ORZHOV", collector_number="7").scryfall_identifier() == {
        "set": "gk2", "collector_number": "7"}
    assert E("x", set_code=" NEO ", collector_number="007").scryfall_identifier() == {"set": "neo", "collector_number": "7"}
    assert E("x", set_code="PLST", collector_number="C15-56").scryfall_identifier()["collector_number"] == "C15-56"
    assert E("x", set_code="neo", collector_number="1*").scryfall_identifier()["collector_number"] == "1★"
    assert E("Signet", set_code="GK2_ORZHOV").scryfall_identifier() == {"name": "Signet", "set": "gk2"}


def test_package_exports():
    import mtg_toolkits

    for name in ("normalize_set_code", "normalize_collector_number", "set_alias_map", "parse_number", "parse_quantity"):
        assert getattr(mtg_toolkits, name) is not None and name in mtg_toolkits.__all__


def test_retry_after_dates_accept_a_naive_now():
    from datetime import datetime

    from mtg_toolkits.http import retry_after_seconds

    assert retry_after_seconds("Wed, 21 Oct 2015 07:28:10 GMT", now=datetime(2015, 10, 21, 7, 28, 0)) == 10.0
