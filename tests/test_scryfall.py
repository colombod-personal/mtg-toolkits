import json

import httpx

from conftest import json_response, make_client
from mtg_toolkits.models import CollectionEntry, Finish
from mtg_toolkits.scryfall import Card, ScryfallClient


def test_card_parsing_single_and_double_faced(cards):
    sol = Card.from_json(cards["sol"])
    assert sol.oracle_text == "{T}: Add {C}{C}." and sol.prices.usd == 1.49 and sol.prices.usd_foil is None
    delver = Card.from_json(cards["delver"])
    assert delver.mana_cost == "{U}" and delver.type_line.startswith("Creature — Human Wizard // ")
    assert "Flying" in delver.oracle_text and delver.colors == ["U"]
    assert delver.image_uris["normal"] == "https://img/delver.jpg"
    assert delver.prices.for_finish(Finish.FOIL) == 4.0


def test_named_sends_required_headers(cards):
    seen = {}

    def handler(request):
        seen.update(request.headers)
        assert request.url.path == "/cards/named" and request.url.params["exact"] == "Sol Ring"
        return json_response(cards["sol"])

    with make_client(ScryfallClient, handler, slow_interval=0) as sf:
        assert sf.named("Sol Ring").name == "Sol Ring"
    assert seen["user-agent"].startswith("mtg-toolkits/") and seen["accept"] == "application/json"


def test_search_paginates_and_handles_no_results(cards):
    def handler(request):
        if request.url.params.get("q") == "nothing":
            return json_response({"object": "error", "status": 404, "details": "No cards found"}, 404)
        if request.url.params.get("page") == "2":
            return json_response({"object": "list", "has_more": False, "data": [cards["delver"]]})
        return json_response({"object": "list", "has_more": True,
                              "next_page": "https://api.scryfall.com/cards/search?q=x&page=2", "data": [cards["sol"]]})

    with make_client(ScryfallClient, handler, slow_interval=0) as sf:
        assert [c.id for c in sf.search("x")] == ["sol-ring-id", "delver-id"]
        assert list(sf.search("nothing")) == []


def test_collection_batches_and_resolves_entries(cards):
    batches = []

    def handler(request):
        ids = json.loads(request.content)["identifiers"]
        batches.append(len(ids))
        found = []
        for ident in ids:
            if ident.get("collector_number") == "263":
                found.append(cards["sol"])
            elif ident.get("name") == "Delver of Secrets":
                found.append(cards["delver"])
        missing = [i for i in ids if i.get("name") == "Nope"]
        return json_response({"object": "list", "data": found, "not_found": missing})

    entries = [CollectionEntry("Sol Ring", set_code="C21", collector_number="263"),
               CollectionEntry("Delver of Secrets"), CollectionEntry("Nope")] * 30
    with make_client(ScryfallClient, handler, slow_interval=0) as sf:
        resolved = sf.resolve_entries(entries)
    assert batches == [75, 15]
    assert resolved[0][1].id == "sol-ring-id" and resolved[1][1].id == "delver-id" and resolved[2][1] is None


def test_iter_bulk_file_reads_gzipped_jsonl(tmp_path, cards):
    import gzip

    from mtg_toolkits.scryfall import iter_bulk_file

    path = tmp_path / "default-cards.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(cards["sol"]) + "\n" + json.dumps(cards["delver"]) + "\n")
    assert [Card.from_json(o).id for o in iter_bulk_file(path)] == ["sol-ring-id", "delver-id"]


def test_download_bulk_uses_jsonl_uri(tmp_path):
    def handler(request):
        if request.url.path == "/bulk-data":
            return json_response({"object": "list", "data": [
                {"type": "oracle_cards", "jsonl_download_uri": "https://data.scryfall.io/oracle-cards/x.jsonl.gz"}]})
        assert request.url.host == "data.scryfall.io"
        return httpx.Response(200, content=b"payload")

    with make_client(ScryfallClient, handler, slow_interval=0) as sf:
        out = sf.download_bulk("oracle_cards", tmp_path / "o.jsonl.gz")
    assert out.read_bytes() == b"payload"


def test_429_backs_off_then_retries(cards, monkeypatch):
    from mtg_toolkits import http

    sleeps = []
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    responses = [httpx.Response(429), json_response(cards["sol"])]
    with make_client(ScryfallClient, lambda r: responses.pop(0), slow_interval=0) as sf:
        assert sf.card("sol-ring-id").name == "Sol Ring"
    assert 30.0 in sleeps
