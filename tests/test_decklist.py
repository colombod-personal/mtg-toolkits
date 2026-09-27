import pytest

from mtg_toolkits import delta
from mtg_toolkits.decklist import parse_text, parse_url
from mtg_toolkits.models import CollectionEntry as E
from mtg_toolkits.models import Finish

ARCHIDEKT_EXPORT = """\
1x Kenrith, the Returned King (cmm) 1 *F* [Commander{top}]
1x Sol Ring (c21) 263 [Ramp]
1x Delver of Secrets // Insectile Aberration (isd) 51 [Maybeboard{noDeck}{noPrice},Creature]
1x Command Tower (clb) 351 *E* [Land] ^Have,#37d67a^
"""


def test_archidekt_text_export():
    deck = parse_text(ARCHIDEKT_EXPORT)
    kenrith, sol, delver, tower = deck.lines
    assert (kenrith.name, kenrith.set_code, kenrith.collector_number, kenrith.finish) == (
        "Kenrith, the Returned King", "cmm", "1", Finish.FOIL)
    assert kenrith.section == "commander"  # "Commander{top}" category
    assert sol.section == "main" and sol.categories == ["Ramp"]
    assert delver.name == "Delver of Secrets // Insectile Aberration" and delver.section == "maybeboard"
    assert tower.finish is Finish.ETCHED and not deck.unparsed


def test_headers_and_plain_formats():
    deck = parse_text("""
Commander
1 Atraxa, Grand Unifier

Deck
4 Lightning Bolt
4x Counterspell [MH2]
1 Sol Ring (C21) 263
// Sideboard
2 Duress
SB: 1 Pyroblast
Maybeboard:
1 Mana Crypt
this line is junk
""")
    assert [(l.name, l.section) for l in deck.lines] == [
        ("Atraxa, Grand Unifier", "commander"),
        ("Lightning Bolt", "main"),
        ("Counterspell", "main"),
        ("Sol Ring", "main"),
        ("Duress", "sideboard"),
        ("Pyroblast", "sideboard"),
        ("Mana Crypt", "maybeboard"),
    ]
    assert deck.lines[2].set_code == "mh2" and deck.lines[3].collector_number == "263"
    assert deck.card_count == 10
    assert [e.name for e in deck.to_entries()][:2] == ["Atraxa, Grand Unifier", "Lightning Bolt"]
    assert deck.unparsed == ["this line is junk"]


@pytest.mark.parametrize("url, expected", [
    ("https://archidekt.com/decks/365563/brago_blink", ("archidekt", "365563")),
    ("archidekt.com/api/decks/42/", ("archidekt", "42")),
    ("https://www.moxfield.com/decks/Ab-cD_9", ("moxfield", "Ab-cD_9")),
    ("https://example.com/decks/1", None),
])
def test_parse_url(url, expected):
    assert parse_url(url) == expected


def test_coverage_report():
    deck = parse_text("4 Lightning Bolt\n1 Sol Ring\n2 Rhystic Study\n")
    owned = [E("Lightning Bolt", 2, set_code="M11"), E("Lightning Bolt", 1, set_code="2XM"), E("Sol Ring", 3)]
    report = {c.entry.name: (c.status, c.have, c.missing) for c in delta.coverage(deck.to_entries(), owned)}
    assert report == {
        "Lightning Bolt": ("partial", 3, 1),
        "Sol Ring": ("owned", 3, 0),
        "Rhystic Study": ("missing", 0, 2),
    }
