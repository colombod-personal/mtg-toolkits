import csv

from conftest import json_response, make_client
from mtg_toolkits import dragonshield
from mtg_toolkits.archidekt import ArchidektClient, write_collection_csv
from mtg_toolkits.models import Finish

DECK = {
    "id": 42, "name": "Test Deck", "deckFormat": 3, "owner": {"username": "alice"}, "description": "",
    "categories": [{"name": "Commander", "includedInDeck": True}, {"name": "Ramp", "includedInDeck": True},
                   {"name": "Maybeboard", "includedInDeck": False}],
    "cards": [
        {"quantity": 1, "modifier": "Foil", "categories": ["Commander"], "deletedAt": None,
         "card": {"uid": "u1", "collectorNumber": "1", "edition": {"editioncode": "cmm", "editionname": "Commander Masters"},
                  "oracleCard": {"name": "Kenrith"}, "prices": {"tcg": 2.5, "ck": 0}}},
        {"quantity": 1, "modifier": "Normal", "categories": ["Ramp"], "deletedAt": None,
         "card": {"uid": "sol-ring-id", "collectorNumber": "263", "edition": {"editioncode": "c21"},
                  "oracleCard": {"name": "Sol Ring"}, "prices": {}}},
        {"quantity": 1, "modifier": "Normal", "categories": ["Maybeboard"], "deletedAt": None,
         "card": {"uid": "u3", "oracleCard": {"name": "Mana Crypt"}}},
    ],
}


def test_get_deck_and_text_export():
    with make_client(ArchidektClient, lambda r: json_response(DECK)) as ak:
        deck = ak.get_deck(42)
    assert deck.owner == "alice" and len(deck.cards) == 3
    assert deck.cards[0].finish is Finish.FOIL and deck.cards[0].prices == {"tcg": 2.5}
    assert [c.name for c in deck.mainboard()] == ["Kenrith", "Sol Ring"]
    assert deck.to_text() == "1 Kenrith (CMM) 1 *F*\n1 Sol Ring (C21) 263"


def test_search_follows_next():
    def handler(request):
        if request.url.params.get("page") == "2":
            return json_response({"results": [{"id": 2}], "next": None})
        return json_response({"results": [{"id": 1}], "next": "https://archidekt.com/api/decks/v3/?page=2"})

    with make_client(ArchidektClient, handler) as ak:
        assert [d["id"] for d in ak.search_decks(ownerUsername="alice")] == [1, 2]


def test_dragonshield_to_archidekt_csv(tmp_path):
    from pathlib import Path

    entries = dragonshield.read(Path(__file__).parent / "fixtures" / "dragonshield_export.csv")
    out = tmp_path / "archidekt.csv"
    assert write_collection_csv(entries, out) == 3
    rows = list(csv.DictReader(out.open()))
    assert rows[1]["Finish"] == "Foil" and rows[1]["Language"] == "JP" and rows[1]["Condition"] == "MP"
    assert rows[0]["Edition Code"] == "c21" and rows[0]["Tags"] == "Binder A"


def test_multi_category_cards_and_to_entries_default_to_mainboard():
    deck_json = {**DECK, "cards": DECK["cards"] + [
        {"quantity": 1, "modifier": "Normal", "categories": ["Ramp", "Maybeboard"], "deletedAt": None,
         "card": {"uid": "u4", "oracleCard": {"name": "Arcane Signet"}}}]}
    with make_client(ArchidektClient, lambda r: json_response(deck_json)) as ak:
        deck = ak.get_deck(42)
    assert "Arcane Signet" not in [c.name for c in deck.mainboard()]  # maybeboard in any category
    assert [e.name for e in deck.to_entries()] == ["Kenrith", "Sol Ring"]
    assert len(deck.to_entries(include_excluded=True)) == 4
