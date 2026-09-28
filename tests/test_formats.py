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
