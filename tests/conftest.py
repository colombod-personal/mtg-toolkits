import json

import httpx
import pytest

SOL_RING = {
    "object": "card", "id": "sol-ring-id", "oracle_id": "o1", "name": "Sol Ring", "lang": "en",
    "set": "c21", "set_name": "Commander 2021", "collector_number": "263", "rarity": "uncommon",
    "layout": "normal", "mana_cost": "{1}", "cmc": 1.0, "type_line": "Artifact",
    "oracle_text": "{T}: Add {C}{C}.", "colors": [], "color_identity": [], "keywords": [],
    "legalities": {"commander": "legal"}, "finishes": ["nonfoil"],
    "prices": {"usd": "1.49", "usd_foil": None, "eur": "1.10", "tix": "0.05"},
    "image_uris": {"normal": "https://img/sol.jpg"}, "scryfall_uri": "https://scryfall.com/card/c21/263",
}
DELVER = {
    "object": "card", "id": "delver-id", "name": "Delver of Secrets // Insectile Aberration", "lang": "ja",
    "set": "isd", "set_name": "Innistrad", "collector_number": "51", "rarity": "common",
    "layout": "transform", "cmc": 1.0, "color_identity": ["U"], "finishes": ["nonfoil", "foil"],
    "prices": {"usd": "0.50", "usd_foil": "4.00", "eur": None},
    "card_faces": [
        {"name": "Delver of Secrets", "mana_cost": "{U}", "type_line": "Creature — Human Wizard",
         "oracle_text": "At the beginning of your upkeep, look at the top card...", "colors": ["U"],
         "power": "1", "toughness": "1", "image_uris": {"normal": "https://img/delver.jpg"}},
        {"name": "Insectile Aberration", "mana_cost": "", "type_line": "Creature — Human Insect",
         "oracle_text": "Flying", "colors": ["U"], "power": "3", "toughness": "2"},
    ],
}


def make_client(cls, handler, **kwargs):
    return cls(client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0, **kwargs)


@pytest.fixture
def cards():
    return {"sol": SOL_RING, "delver": DELVER}


def json_response(data, status=200):
    return httpx.Response(status, content=json.dumps(data), headers={"content-type": "application/json"})
