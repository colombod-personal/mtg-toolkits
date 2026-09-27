from datetime import date
from pathlib import Path

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
