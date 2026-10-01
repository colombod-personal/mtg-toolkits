import pytest

from mtg_toolkits.normalize import MAX_QUANTITY, parse_number, parse_quantity


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
