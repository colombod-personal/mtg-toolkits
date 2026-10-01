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
    assert batches == [3]  # duplicates sent once; "Nope" was already looked up by name, so no retry
    assert resolved[0].card.id == "sol-ring-id" and resolved[0].method == "set_number"
    assert resolved[1].card.id == "delver-id" and resolved[1].method == "name"
    assert resolved[2].card is None and resolved[2].method is None


def test_collection_splits_into_batches_of_75():
    batches = []

    def handler(request):
        batches.append(len(json.loads(request.content)["identifiers"]))
        return json_response({"object": "list", "data": [], "not_found": []})

    with make_client(ScryfallClient, handler, slow_interval=0) as sf:
        sf.resolve_entries([CollectionEntry(f"Card {i}") for i in range(100)], fallback=False)
    assert batches == [75, 25]


def test_fallback_to_name_and_set(cards):
    """A collector number Scryfall doesn't know still resolves by name within the set."""
    def handler(request):
        found = [cards["delver"] for i in json.loads(request.content)["identifiers"]
                 if i.get("name") == "Delver of Secrets" and i.get("set") == "isd"]
        return json_response({"object": "list", "data": found, "not_found": []})

    entry = CollectionEntry("Delver of Secrets // Insectile Aberration", set_code="ISD", collector_number="51a")
    with make_client(ScryfallClient, handler, slow_interval=0) as sf:
        [res] = sf.resolve_entries([entry])
    assert res.card.id == "delver-id" and res.method == "name_set"


def test_fallback_never_resends_an_identifier_that_already_missed():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["identifiers"])
        return json_response({"object": "list", "data": [], "not_found": []})

    no_number = CollectionEntry("Nope", set_code="XXX")  # primary is already name + set
    no_set = CollectionEntry("Nada")  # primary is already the name alone
    with make_client(ScryfallClient, handler, slow_interval=0) as sf:
        results = sf.resolve_entries([no_number, no_set])
    assert [r.card for r in results] == [None, None]
    assert sent == [[{"name": "Nope", "set": "xxx"}, {"name": "Nada"}], [{"name": "Nope"}]]


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


def test_enrich_takes_the_only_finish_a_printing_has(cards):
    from mtg_toolkits.enrich import enrich

    etched = dict(cards["sol"], id="etched-id", collector_number="512", finishes=["etched"],
                  prices={"usd_etched": "0.55"})

    def handler(request):
        return json_response({"object": "list", "data": [etched], "not_found": []})

    entry = CollectionEntry("Sol Ring", set_code="C21", collector_number="512")
    with make_client(ScryfallClient, handler, slow_interval=0) as sf:
        [item] = enrich([entry], sf)
    assert item.entry.finish is Finish.ETCHED and item.unit_price == 0.55 and item.entry.scryfall_id == "etched-id"


def test_resolve_offline_matches_like_the_api(cards):
    from mtg_toolkits.scryfall import resolve_offline

    bulk = [Card.from_json(cards["sol"]), Card.from_json(cards["delver"])]
    entries = [
        CollectionEntry("Sol Ring", set_code="C21", collector_number="263"),
        CollectionEntry("Delver of Secrets // Insectile Aberration", set_code="ISD", collector_number="999"),
        CollectionEntry("Delver of Secrets", set_code="XXX"),
        CollectionEntry("Nope"),
    ]
    got = [(r.card.id if r.card else None, r.method) for r in resolve_offline(entries, bulk)]
    assert got == [("sol-ring-id", "set_number"), ("delver-id", "name_set"), ("delver-id", "name"), (None, None)]


def test_non_json_error_raises_api_error():
    import pytest

    from mtg_toolkits.http import ApiError

    with make_client(ScryfallClient, lambda r: httpx.Response(404, text="<html>nope</html>"), slow_interval=0) as sf:
        with pytest.raises(ApiError) as exc:
            sf.card("x")
    assert exc.value.status_code == 404


def test_search_with_zero_limit_makes_no_request(cards):
    calls = []

    def handler(request):
        calls.append(request)
        return json_response({"object": "list", "has_more": False, "data": [cards["sol"]]})

    with make_client(ScryfallClient, handler, slow_interval=0) as sf:
        assert list(sf.search("x", limit=0)) == [] and calls == []
        assert len(list(sf.search("x", limit=1))) == 1


def _printing(set_code, number, name="X", lang="en"):
    return Card.from_json({"id": f"{set_code}-{number}-{lang}", "name": name, "set": set_code,
                           "collector_number": number, "lang": lang})


def test_offline_matching_normalises_set_codes_and_numbers():
    from mtg_toolkits.scryfall import resolve_offline

    bulk = [_printing("gk2", "7", "Orzhov Signet"), _printing("neo", "7"), _printing("neo", "123a"),
            _printing("neo", "1★"), _printing("plst", "C15-56")]
    entries = [CollectionEntry("Orzhov Signet", set_code="GK2_ORZHOV", collector_number="7"),
               CollectionEntry("X", set_code="NEO", collector_number="007"),
               CollectionEntry("X", set_code=" Neo ", collector_number="123A"),
               CollectionEntry("X", set_code="neo", collector_number="1*"),
               CollectionEntry("X", set_code="PLST", collector_number="c15-56")]
    got = [(r.card.id if r.card else None, r.method) for r in resolve_offline(entries, bulk, fallback=False)]
    assert got == [("gk2-7-en", "set_number"), ("neo-7-en", "set_number"), ("neo-123a-en", "set_number"),
                   ("neo-1★-en", "set_number"), ("plst-C15-56-en", "set_number")]
    [res] = resolve_offline([CollectionEntry("Orzhov Signet", set_code="GK2_ORZHOV")], bulk)
    assert res.method == "name_set" and res.card.id == "gk2-7-en"


def test_online_matching_translates_dragon_shield_set_codes():
    sent = []

    def handler(request):
        ids = json.loads(request.content)["identifiers"]
        sent.append(ids)
        found = [{"id": "signet", "name": "Orzhov Signet", "set": "gk2", "collector_number": "7"}
                 for i in ids if i == {"set": "gk2", "collector_number": "7"}]
        return json_response({"object": "list", "data": found, "not_found": []})

    with make_client(ScryfallClient, handler, slow_interval=0) as sf:
        [res] = sf.resolve_entries([CollectionEntry("Orzhov Signet", set_code="GK2_ORZHOV", collector_number="7")])
    assert (res.card.id, res.method) == ("signet", "set_number") and sent == [[{"set": "gk2", "collector_number": "7"}]]


def test_matching_prefers_the_entry_language_then_english():
    from mtg_toolkits.scryfall import resolve_offline

    bulk = [_printing("neo", "1", "Bolt", "ja"), _printing("neo", "1", "Bolt", "en"), _printing("neo", "1", "Bolt", "de")]
    for fallback_only in (False, True):
        entries = [CollectionEntry("Bolt", set_code="neo", collector_number=None if fallback_only else "1", language=lang)
                   for lang in ("en", "de", "fr")]
        assert [r.card.lang for r in resolve_offline(entries, bulk)] == ["en", "de", "en"]
        assert [r.card.lang for r in resolve_offline([CollectionEntry("Bolt", language="ja")], bulk)] == ["ja"]
    assert resolve_offline([CollectionEntry("Bolt", language="fr")], bulk[:1])[0].card.lang == "ja"  # only one


def test_index_keys_prefilter_a_bulk_stream(cards):
    from mtg_toolkits.scryfall import card_matches_keys, index_keys, resolve_offline

    entries = [CollectionEntry("Orzhov Signet", set_code="GK2_ORZHOV", collector_number="007"),
               CollectionEntry("Insectile Aberration"), CollectionEntry("Anything", scryfall_id="sol-ring-id")]
    keys = index_keys(entries)
    bulk = [{"id": "signet", "name": "Orzhov Signet", "set": "gk2", "collector_number": "7"},
            {"id": "other-signet", "name": "Orzhov Signet", "set": "rav", "collector_number": "1"},  # name fallback
            cards["delver"], cards["sol"], {"id": "bolt", "name": "Lightning Bolt", "set": "m11", "collector_number": "149"}]
    kept = [c for c in bulk if card_matches_keys(c, keys)]
    assert [c["id"] for c in kept] == ["signet", "other-signet", "delver-id", "sol-ring-id"]
    assert card_matches_keys(Card.from_json(cards["sol"]), keys)
    full = resolve_offline(entries, [Card.from_json(c) for c in bulk])
    assert [(r.card.id, r.method) for r in resolve_offline(entries, [Card.from_json(c) for c in kept])] == [
        (r.card.id, r.method) for r in full]
    assert index_keys(entries, fallback=False) < keys
