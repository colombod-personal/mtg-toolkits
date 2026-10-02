from datetime import date

import pytest

from mtg_toolkits import dragonshield, moxfield
from mtg_toolkits.models import CollectionEntry, Condition, Finish

EXPORT = """\
"Count","Tradelist Count","Name","Edition","Condition","Language","Foil","Tags","Last Modified","Collector Number","Alter","Proxy","Purchase Price"
"3","1","Sol Ring","c21","Near Mint","English","","Ramp","2024-02-17 10:12:00.000000","263","False","False","1.50"
"1","0","Delver of Secrets // Insectile Aberration","isd","Lightly Played","Japanese","foil","","2023-01-10 09:00:00.000000","51","False","False",""
"1","0","Accursed Marauder","mh3","NM","en","etched","","","512","False","False","0,80"
"""


def test_parse_moxfield_export():
    sol, delver, marauder = moxfield.parse(EXPORT)
    assert (sol.name, sol.quantity, sol.trade_quantity, sol.set_code, sol.collector_number) == ("Sol Ring", 3, 1, "c21", "263")
    assert (sol.condition, sol.finish, sol.language, sol.purchase_price, sol.folder) == (
        Condition.NEAR_MINT, Finish.NONFOIL, "en", 1.5, "Ramp")
    assert sol.purchase_date == date(2024, 2, 17)
    assert (delver.name, delver.finish, delver.condition, delver.language) == (
        "Delver of Secrets // Insectile Aberration", Finish.FOIL, Condition.EXCELLENT, "ja")
    assert (marauder.finish, marauder.condition, marauder.purchase_price) == (Finish.ETCHED, Condition.NEAR_MINT, 0.8)
    assert sol.scryfall_identifier() == {"set": "c21", "collector_number": "263"}


def test_round_trip():
    entries = moxfield.parse(EXPORT)
    again = moxfield.parse(moxfield.dumps(entries))
    key = lambda e: (e.name, e.quantity, e.trade_quantity, e.set_code, e.collector_number, e.finish, e.condition,  # noqa: E731
                     e.language, e.purchase_price)
    assert [key(e) for e in again] == [key(e) for e in entries]


def test_dragon_shield_to_moxfield(tmp_path):
    ds = dragonshield.parse('"sep=,"\r\nFolder Name,Quantity,Trade Quantity,Card Name,Set Code,Set Name,Card Number,'
                            'Condition,Printing,Language,Price Bought,Date Bought,LOW,MID,MARKET\r\n'
                            'Binder,2,0,Sol Ring,C21,Commander 2021,263,Played,Foil,German,2.00,2023-05-01,1,2,3\r\n')
    out = tmp_path / "moxfield.csv"
    assert moxfield.write(ds, out) == 1
    (e,) = moxfield.read(out)
    assert (e.name, e.quantity, e.set_code, e.finish, e.condition, e.language, e.folder) == (
        "Sol Ring", 2, "c21", Finish.FOIL, Condition.PLAYED, "de", "Binder")


def test_rejects_other_files():
    with pytest.raises(ValueError, match="Moxfield"):
        moxfield.parse("a,b\n1,2\n")


def test_lenient_values():
    text = "Count,Name,Edition,Condition,Foil,Language\n2,Lightning Bolt,M11,MP,Foil,French\n1,Island,,,,\n"
    bolt, island = moxfield.parse(text)
    assert (bolt.set_code, bolt.condition, bolt.finish, bolt.language) == ("m11", Condition.LIGHT_PLAYED, Finish.FOIL, "fr")
    assert (island.set_code, island.condition, island.finish, island.language) == (None, Condition.NEAR_MINT, Finish.NONFOIL, "en")
    assert CollectionEntry(name="x").condition is Condition.NEAR_MINT


MOX_HEADER = ",".join(moxfield.COLUMNS) + "\n"


def test_rows_with_more_fields_than_the_header():
    [trailing, unquoted] = moxfield.parse(MOX_HEADER + "1,0,Bolt,m11,NM,English,,,,149,False,False,1.00,\n"
                                          "1,0,Bolt,m11,NM,English,,,,149,False,False,$1,000\n")
    assert (trailing.name, trailing.purchase_price) == ("Bolt", 1.0)
    assert (unquoted.name, unquoted.purchase_price) == ("Bolt", 1.0)  # overflow ("000") is ignored


@pytest.mark.parametrize("price, expected", [("1,234.50", 1234.5), ("€1.50", 1.5), ("1.234,50", 1234.5), ("0,80", 0.8)])
def test_localised_prices(price, expected):
    [e] = moxfield.parse(MOX_HEADER + f'1,0,Bolt,m11,NM,English,,,,149,False,False,"{price}"\n')
    assert e.purchase_price == expected


def test_integer_valued_float_count_and_bad_counts():
    [e] = moxfield.parse("Count,Name\n2.0,Bolt\n")
    assert e.quantity == 2
    for bad in ("inf", "1e30", "abc"):
        with pytest.raises(ValueError, match="quantity"):
            moxfield.parse(f"Count,Name\n{bad},Bolt\n")


def test_oversized_field_is_a_value_error():
    with pytest.raises(ValueError):
        moxfield.parse('Count,Name\n1,"' + "x" * 200_000 + '"\n')


def test_dragon_shield_set_codes_become_scryfall_codes_and_write_back_as_read():
    from mtg_toolkits import moxfield

    text = ("Count,Tradelist Count,Name,Edition,Condition,Language,Foil,Tags,Last Modified,Collector Number\n"
            "1,0,Belfry Spirit,GK2_ORZHOV,Near Mint,English,,,,29\n"
            "1,0,Sol Ring,C21,Near Mint,English,,,,263\n")
    belfry, sol = moxfield.parse(text)
    assert (belfry.set_code, sol.set_code) == ("gk2", "c21")
    out = moxfield.dumps([belfry, sol])
    assert ",gk2_orzhov," in out.lower() and ",c21," in out
