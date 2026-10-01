import pytest

from mtg_toolkits import formats
from mtg_toolkits.models import Condition, Finish

DS = ('"sep=,"\r\nFolder Name,Quantity,Trade Quantity,Card Name,Set Code,Set Name,Card Number,Condition,Printing,'
      'Language,Price Bought,Date Bought,LOW,MID,MARKET\r\n'
      'Binder,2,0,Sol Ring,C21,Commander 2021,263,NearMint,Foil,English,2.00,2023-05-01,1.00,2.00,3.00\r\n'
      'Binder,1,0,Lightning Bolt,M11,Magic 2011,149,Played,Normal,German,,,,,\r\n'
      'Trade,3,1,Sol Ring,C21,Commander 2021,263,Mint,Foil,English,,,,,\r\n')
MOX = ("Count,Tradelist Count,Name,Edition,Condition,Language,Foil,Tags,Last Modified,Collector Number,Alter,Proxy,Purchase Price\n"
       "1,0,Sol Ring,c21,Near Mint,English,foil,,,263,False,False,\n")


def test_detect():
    assert formats.detect(DS) == "dragonshield"
    assert formats.detect(DS.split("\r\n", 1)[1]) == "dragonshield"  # without the sep line
    assert formats.detect(MOX) == "moxfield"
    assert formats.detect("﻿" + MOX) == "moxfield"
    assert formats.detect(formats.dumps_generic([])) == "csv"
    assert formats.detect("hello\n") is None
    with pytest.raises(ValueError, match="Dragon Shield, Moxfield, Generic CSV"):
        formats.parse("hello\n")


@pytest.mark.parametrize("target", ["dragonshield", "moxfield", "csv"])
def test_every_readable_format_round_trips_the_essentials(target):
    _, entries = formats.parse(DS)
    fmt, back = formats.parse(formats.FORMATS[target].dumps(entries))
    assert fmt == target
    essentials = lambda e: (e.name, e.quantity, (e.set_code or "").lower(), e.collector_number, e.finish, e.language)  # noqa: E731
    assert [essentials(e) for e in back] == [essentials(e) for e in entries]


def test_generic_csv_is_lossless():
    _, entries = formats.parse(DS)
    entries[0].scryfall_id = "abc-123"
    _, back = formats.parse(formats.dumps_generic(entries))
    fields = lambda e: (e.name, e.quantity, e.trade_quantity, e.set_code, e.set_name, e.collector_number, e.finish,  # noqa: E731
                        e.condition, e.language, e.folder, e.purchase_price, e.purchase_date, e.scryfall_id)
    assert [fields(e) for e in back] == [fields(e) for e in entries]
    assert back[1].condition is Condition.PLAYED


def test_text_list_merges_conditions_and_folders():
    _, entries = formats.parse(DS)
    assert formats.dumps_text(entries) == "5 Sol Ring (C21) 263 *F*\n1 Lightning Bolt (M11) 149\n"


def test_archidekt_export():
    _, entries = formats.parse(DS)
    text = formats.FORMATS["archidekt"].dumps(entries)
    assert text.splitlines()[0].startswith("Quantity,Name,Finish,Condition")
    assert "2,Sol Ring,Foil,NM" in text and entries[0].finish is Finish.FOIL


def test_detect_any_declared_separator():
    semicolon = '"sep=;"\r\nFolder Name;Quantity;Card Name\r\nBinder;2;Sol Ring\r\n'
    assert formats.detect(semicolon) == "dragonshield"
    fmt, entries = formats.parse(semicolon)
    assert fmt == "dragonshield" and (entries[0].name, entries[0].quantity) == ("Sol Ring", 2)
    # a separator line alone doesn't make a file Dragon Shield: it needs a Card Name column
    assert formats.detect("sep=;\na;b\n") is None
    assert formats.detect('"sep=,"\r\nQuantity,Name\r\n1,Sol Ring\r\n') is None


def test_generic_csv_keeps_source_prices_and_extras():
    rows = ("x,1,0,Belfry Spirit,GK2_ORZHOV,Guild Kit,29,Mint,Normal,English,,,1.00,2.00,3.00\r\n"
            "x,1,0,Accursed Marauder,MH3,Modern Horizons 3,512,Mint,,English,,,,,\r\n"
            "x,1,0,Lightning Bolt,M11,Magic 2011,149,Mint,Foil Etched,English,,,,,\r\n")
    ds = DS.split("\r\n", 2)[0] + "\r\n" + DS.split("\r\n", 2)[1] + "\r\n" + rows
    _, entries = formats.parse(ds)
    assert entries[0].source_prices and all(e.extra for e in entries)  # aliased set code, blank/named Printing
    _, back = formats.parse(formats.dumps_generic(entries))
    assert [(e.source_prices, e.extra) for e in back] == [(e.source_prices, e.extra) for e in entries]
    # and a Dragon Shield export rebuilt from the generic copy is byte-identical
    assert formats.FORMATS["dragonshield"].dumps(back) == formats.FORMATS["dragonshield"].dumps(entries)


GENERIC = ",".join(formats.GENERIC_COLUMNS) + "\n"


def test_generic_csv_is_lenient():
    rows = ['1.0,0,Bolt,m11,,149,nonfoil,near_mint,en,,,,,,', '1,0,Bolt,m11,,149,Foil,near_mint,en,,,,,,',
            '1,0,Bolt,m11,,149,nonfoil,NM,en,,,,,,', '1,0,Bolt,m11,,149,nonfoil,near_mint,en,,"1,50",,,,',
            '1,0,Bolt,m11,,149, Foil Etched ,Lightly Played,en,,$2.00,,,,', '1,0,Bolt,m11,,149,,LightPlayed,en,,,,,,',
            '1,0,Bolt,m11,,149,,DMG,en,,,,,,,overflow']
    fmt, entries = formats.parse(GENERIC + "\n".join(rows) + "\n")
    assert fmt == "csv"
    assert [(e.quantity, e.finish, e.condition, e.purchase_price) for e in entries] == [
        (1, Finish.NONFOIL, Condition.NEAR_MINT, None),
        (1, Finish.FOIL, Condition.NEAR_MINT, None),
        (1, Finish.NONFOIL, Condition.NEAR_MINT, None),
        (1, Finish.NONFOIL, Condition.NEAR_MINT, 1.5),
        (1, Finish.ETCHED, Condition.EXCELLENT, 2.0),
        (1, Finish.NONFOIL, Condition.LIGHT_PLAYED, None),
        (1, Finish.NONFOIL, Condition.POOR, None),
    ]


@pytest.mark.parametrize("row", [
    "1,0,Bolt,,,,sparkly,,,,,,,,", "1,0,Bolt,,,,,shredded,,,,,,,", "abc,0,Bolt,,,,,,,,,,,,",
    "inf,0,Bolt,,,,,,,,,,,,", "99999999999999999999999,0,Bolt,,,,,,,,,,,,", "1,0,Bolt,,,,,,,,,,,[1],",
    '1,0,Bolt,,,,,,,,,,,"{""a"": null}",', '1,0,Bolt,,,,,,,,,,,"{""a"": ""x""}",', "1,0,Bolt,,,,,,,,,,,,[1]",
    '1,0,Bolt,,,,,,,,,,,,"{""a"": ', "1,0,Bolt,,,,,,,,,not-a-date,,,", '"' + "x" * 200_000 + '",0,Bolt,,,,,,,,,,,,',
])
def test_malformed_generic_csv_raises_value_error(row):
    with pytest.raises(ValueError):
        formats.parse(GENERIC + row + "\n")


def test_generic_extra_null_becomes_empty_string():
    [e] = formats.parse_generic(GENERIC + '1,0,Bolt,,,,,,,,,,,,"{""a"": null, ""b"": 2}"\n')
    assert e.extra == {"a": "", "b": "2"}


def test_detect_tab_separator_line():
    text = "sep=\t\nFolder Name\tQuantity\tCard Name\nBinder\t2\tSol Ring\n"
    assert formats.detect(text) == "dragonshield"
    assert formats.parse(text)[1][0].quantity == 2


def test_oversized_header_is_unrecognised():
    with pytest.raises(ValueError, match="Unrecognised"):
        formats.parse('"' + "x" * 200_000 + '",Card Name\n')
