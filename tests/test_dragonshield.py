from datetime import date
from pathlib import Path

import pytest

from mtg_toolkits import dragonshield
from mtg_toolkits.models import Condition, Finish

FIXTURE = Path(__file__).parent / "fixtures" / "dragonshield_export.csv"


def test_parse_export():
    entries = dragonshield.read(FIXTURE)
    assert len(entries) == 3
    sol, delver, bolt = entries
    assert (sol.name, sol.quantity, sol.trade_quantity, sol.set_code, sol.collector_number) == ("Sol Ring", 2, 1, "C21", "263")
    assert sol.purchase_price == 1.5 and sol.purchase_date == date(2023, 5, 1)
    assert sol.source_prices == {"low": 1.2, "mid": 1.6, "market": 1.55}
    assert delver.finish is Finish.FOIL and delver.condition is Condition.LIGHT_PLAYED
    assert delver.language == "ja" and delver.purchase_date == date(2022, 6, 3)
    assert bolt.language == "de" and bolt.purchase_price == 1.25 and bolt.folder == "Trade"


def test_parse_without_sep_line_and_reordered_columns():
    text = "Card Name;Quantity;Printing\nSol Ring;3;Foil\n"
    text = "sep=;\n" + text
    [e] = dragonshield.parse(text)
    assert (e.name, e.quantity, e.finish) == ("Sol Ring", 3, Finish.FOIL)
    [e] = dragonshield.parse("Quantity,Card Name\n4,Island\n")
    assert (e.name, e.quantity) == ("Island", 4)


def test_roundtrip():
    entries = dragonshield.read(FIXTURE)
    again = dragonshield.parse(dragonshield.dumps(entries))
    assert [(e.name, e.quantity, e.finish, e.condition, e.language, e.purchase_date) for e in again] == [
        (e.name, e.quantity, e.finish, e.condition, e.language, e.purchase_date) for e in entries
    ]


REAL_EXPORT = (
    '"sep=,"\r\n'
    "Folder Name,Quantity,Trade Quantity,Card Name,Set Code,Set Name,Card Number,Condition,Printing,Language,"
    "Price Bought,Date Bought,LOW,MID,MARKET\r\n"
    "my cards,1,0,Altar of Bhaal // Bone Offering,AFR,Adventures in the Forgotten Realms,92,Mint,Normal,English,"
    "0.10,2022-12-03,0.01,0.20,0.15\r\n"
    "my cards,1,0,Accursed Marauder,MH3,Modern Horizons 3,512,Mint,,English,0.50,2024-06-20,0.30,0.60,0.55\r\n"
    "my cards,1,0,Elesh Norn,ONE,Phyrexia: All Will Be One,300,Mint,Oilslick Foil,Italian,5.00,2023-02-10,4.00,6.00,5.00\r\n"
    "my cards,1,0,Belfry Spirit,GK2_ORZHOV,Guild Kit: Orzhov,29,Mint,Normal,English,0.10,2022-11-20,0.05,0.20,0.10\r\n"
    "my cards,1,0,Command Beacon,PLST,The List,C15-56,NearMint,,English,1.00,2022-11-20,0.50,1.20,1.00\r\n"
)


def test_real_export_quirks():
    altar, marauder, norn, belfry, beacon = dragonshield.parse(REAL_EXPORT)
    assert altar.name == "Altar of Bhaal // Bone Offering"  # quoted sep line handled, full DFC name kept
    assert marauder.finish is Finish.NONFOIL and marauder.extra == {"Printing": ""}
    assert norn.finish is Finish.FOIL and norn.extra["Printing"] == "Oilslick Foil" and norn.language == "it"
    assert belfry.set_code == "gk2" and belfry.extra["Set Code"] == "GK2_ORZHOV"
    assert beacon.collector_number == "C15-56" and beacon.condition is Condition.NEAR_MINT


def test_real_export_roundtrip_is_lossless():
    assert dragonshield.dumps(dragonshield.parse(REAL_EXPORT)) == REAL_EXPORT


def test_variant_layout_is_normalised_without_data_loss():
    variant = "sep=,\nQuantity,Card Name,Printing\n2,Sol Ring,Foil\n"
    out = dragonshield.dumps(dragonshield.parse(variant))
    assert out.startswith('"sep=,"\r\n' + ",".join(dragonshield.COLUMNS) + "\r\n")
    [e] = dragonshield.parse(out)
    assert (e.name, e.quantity, e.finish) == ("Sol Ring", 2, Finish.FOIL)


def test_quantity_zero_stays_zero():
    [zero, blank] = dragonshield.parse("Card Name,Quantity\nSol Ring,0\nIsland,\n")
    assert (zero.quantity, blank.quantity) == (0, 1)


def test_columns_the_app_does_not_export_are_kept():
    header = ",".join(dragonshield.COLUMNS)
    row = "Binder,2,0,Sol Ring,C21,Commander 2021,263,NearMint,Normal,English,,,,,"
    with_notes = f'"sep=,"\r\n{header},Notes\r\n{row},"signed, by the artist"\r\n'
    [e] = dragonshield.parse(with_notes)
    assert e.extra == {"Notes": "signed, by the artist"}
    assert dragonshield.dumps([e]) == with_notes  # appended columns come back byte for byte
    plain = dragonshield.parse(f'"sep=,"\r\n{header}\r\n{row}\r\n')
    assert dragonshield.dumps(plain + [e]).splitlines()[1].endswith(",MARKET,Notes")  # blank for entries without it


HEADER = ",".join(dragonshield.COLUMNS) + "\n"


def test_tab_separator_line():
    text = "sep=\t\n" + HEADER.replace(",", "\t") + "F\t1\t0\tBolt\tM11\tM11\t149\tNearMint\tNormal\tEnglish\t1,50\t\t\t\t\n"
    [e] = dragonshield.parse(text)
    assert (e.name, e.collector_number, e.purchase_price) == ("Bolt", "149", 1.5)
    [e] = dragonshield.parse('"sep=\t"\r\n' + HEADER.replace(",", "\t") + "F\t2\t0\tBolt\n")
    assert (e.name, e.quantity) == ("Bolt", 2)


@pytest.mark.parametrize("price, expected", [("1.234,50", 1234.5), ("1,234", 1234.0), ("1,234.50", 1234.5),
                                             ("€1,50", 1.5), ("1,50", 1.5)])
def test_localised_prices(price, expected):
    [e] = dragonshield.parse(HEADER + f'F,1,0,Bolt,M11,M11,149,NearMint,Normal,English,"{price}",,"{price}",,\n')
    assert e.purchase_price == expected and e.source_prices == {"low": expected}


def test_rows_with_more_fields_than_the_header():
    [e] = dragonshield.parse(HEADER + "F,1,0,Bolt,M11,M11,149,NearMint,Normal,English,,,,,,overflow\n")
    assert (e.name, e.extra) == ("Bolt", {})


def test_unknown_condition_and_language_round_trip():
    text = ('"sep=,"\r\n' + HEADER.rstrip("\n") + "\r\n"
            "F,1,0,Bolt,M11,M11,149,Mint/NM,Normal,Klingon,,,,,\r\n"
            "F,1,0,Bolt,M11,M11,149,NearMint,Normal,Phyrexian,,,,,\r\n")
    odd, phyrexian = dragonshield.parse(text)
    assert (odd.condition, odd.language) == (Condition.NEAR_MINT, "en")
    assert odd.extra == {"Condition": "Mint/NM", "Language": "Klingon"}
    assert phyrexian.language == "ph" and phyrexian.extra == {}
    assert dragonshield.dumps([odd, phyrexian]) == text
    odd.condition, odd.language = Condition.PLAYED, "de"  # an edited value wins over the original string
    assert ",Played,Normal,German," in dragonshield.dumps([odd])


@pytest.mark.parametrize("code, name", [("ph", "Phyrexian"), ("he", "Hebrew"), ("la", "Latin"), ("ar", "Arabic"),
                                        ("sa", "Sanskrit"), ("grc", "Ancient Greek")])
def test_rare_languages(code, name):
    assert dragonshield.LANGUAGES[name.lower()] == code and dragonshield.LANGUAGE_NAMES[code] == name


@pytest.mark.parametrize("qty", ["1e30", "inf", "abc", "99999999999999999999999", "1.5"])
def test_bad_quantity_is_a_value_error(qty):
    with pytest.raises(ValueError, match="quantity"):
        dragonshield.parse(f"Card Name,Quantity\nSol Ring,{qty}\n")


def test_oversized_field_is_a_value_error():
    with pytest.raises(ValueError):
        dragonshield.parse('Card Name,Quantity\n"' + "x" * 200_000 + '",1\n')
