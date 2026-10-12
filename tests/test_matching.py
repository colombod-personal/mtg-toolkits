"""The matching ladder (mtg_toolkits.matching): id, set + number (with a fallback set), name + set,
name + collector number, name; and the stated rule for picking a printing. Synthetic printings only."""

import random

from mtg_toolkits.matching import (EXACT_METHODS, AliasProof, Printing, PrintingIndex, choose, derive_set_aliases, index_keys,
                                  pick)
from mtg_toolkits.models import CollectionEntry, Finish
from mtg_toolkits.normalize import fallback_set_code, set_code_fallbacks, normalize_set_code, set_alias_map
from mtg_toolkits.scryfall import Card, card_matches_keys, resolve_offline


def p(id, name, set_code, number, lang="en", usd=None, foil=None, etched=None, faces=()):
    return Printing(id, name, set_code, number, lang, usd, foil, etched, faces)


# What the catalog holds; the shapes of a Dragon Shield export of 14,597 rows whose 17 unmatched rows were:
# MB1 numbers up to 1607, VTHB/PHED/FWB/PAGL codes, and a few cards no catalog has.
CATALOG = [
    p("dax-258", "Daxos, Blessed by the Sun", "thb", "258", usd=0.40),
    p("dax-7", "Daxos, Blessed by the Sun", "thb", "7", usd=0.10),
    p("dax-x", "Daxos, Blessed by the Sun", "pthb", "7p", usd=2.00),
    p("cs-cmr", "Counterspell", "plst", "CMR-395", usd=1.20),
    p("cs-mh2", "Counterspell", "mh2", "267", usd=0.90, foil=2.5),
    p("cs-a25", "Counterspell", "a25", "50", usd=1.10, foil=4.0),
    p("bolt-m11", "Lightning Bolt", "m11", "149", usd=1.00),
    p("bolt-2xm", "Lightning Bolt", "2xm", "117", usd=2.00),
    p("fire", "Fire // Ice", "mh2", "290", usd=0.30, faces=("Fire", "Ice")),
]


def match(entry, printings=CATALOG, **kwargs):
    m = PrintingIndex(printings).match(entry, **kwargs)
    return (m.printing.id if m.printing else None, m.method)


def test_dragon_shield_variant_set_is_found_by_the_code_fallback_and_without_it_by_name_and_number():
    # VTHB is Dragon Shield's own code: its fallback is thb, so the printing is the one the file names.
    assert match(CollectionEntry("Daxos, Blessed by the Sun", set_code="VTHB", collector_number="258")) == ("dax-258", "set_number")
    # a code nobody listed: the card's name and that collector number are the printing
    assert match(CollectionEntry("Daxos, Blessed by the Sun", set_code="VXXX", collector_number="258")) == ("dax-258", "name_number")


def test_fallback_codes_use_their_set_only_when_the_code_has_no_printing():
    entry = CollectionEntry("Counterspell", set_code="MB1", collector_number="1607")
    # no printing is numbered 1607: the card in The List, found by name in the set MB1 became
    assert match(entry) == ("cs-cmr", "name_set")
    assert fallback_set_code("MB1") == "plst" and fallback_set_code(" fmb1 ") == "plst" and fallback_set_code("thb") is None
    # a catalog that does hold a printing under the old code wins over the alias
    old = p("mb1-1607", "Counterspell", "mb1", "1607", usd=5.0)
    assert match(entry, CATALOG + [old]) == ("mb1-1607", "set_number")
    # the code and the number the list uses in the set it falls back to
    assert match(CollectionEntry("Counterspell", set_code="PLIST", collector_number="CMR-395")) == ("cs-cmr", "set_number")
    assert match(CollectionEntry("Counterspell", set_code="MB1", collector_number="CMR-395")) == ("cs-cmr", "set_number")


def test_the_exact_methods_are_only_the_ones_that_name_the_printing():
    assert EXACT_METHODS == ("id", "set_number")
    assert PrintingIndex(CATALOG).match(CollectionEntry("Counterspell", scryfall_id="cs-a25")).exact
    assert not PrintingIndex(CATALOG).match(CollectionEntry("Counterspell", set_code="MB1", collector_number="1")).exact


def test_a_card_in_no_catalog_is_not_found_and_not_guessed():
    assert match(CollectionEntry("Nonexistent Marauder", set_code="FWB", collector_number="12")) == (None, None)
    assert match(CollectionEntry("Nonexistent Marauder")) == (None, None)


def test_name_and_set_beats_name_and_number_and_name_alone_is_last():
    # the set is known but the number is not that set's: the set wins over the same number elsewhere
    assert match(CollectionEntry("Lightning Bolt", set_code="2XM", collector_number="149")) == ("bolt-2xm", "name_set")
    assert match(CollectionEntry("Lightning Bolt", set_code="ZZZ", collector_number="149")) == ("bolt-m11", "name_number")
    assert match(CollectionEntry("Lightning Bolt", set_code="ZZZ", collector_number="9999")) == ("bolt-m11", "name")
    assert match(CollectionEntry("Lightning Bolt")) == ("bolt-m11", "name")


def test_a_double_faced_or_split_card_is_found_by_either_face():
    assert match(CollectionEntry("Ice", set_code="ZZZ", collector_number="290")) == ("fire", "name_number")
    assert match(CollectionEntry("Fire // Ice")) == ("fire", "name")


def test_fallback_off_stops_at_the_steps_that_name_a_printing():
    assert match(CollectionEntry("Counterspell", set_code="MB1", collector_number="1607"), fallback=False) == (None, None)
    assert match(CollectionEntry("Daxos, Blessed by the Sun", set_code="VTHB", collector_number="258"), fallback=False) == (
        "dax-258", "set_number")


def test_the_rule_picks_the_language_then_the_cheapest_in_the_finish_then_a_fixed_order():
    cands = [p("a", "X", "s2", "1", usd=3.0, foil=1.0), p("b", "X", "s1", "1", usd=2.0, foil=9.0),
             p("c", "X", "s3", "1", usd=None, foil=None), p("d", "X", "s0", "1", lang="de", usd=9.0)]
    assert choose(cands).id == "b"  # cheapest English nonfoil
    assert choose(cands, finish=Finish.FOIL).id == "a"  # cheapest in the row's finish
    assert choose(cands, language="de").id == "d"  # the row's language first
    assert choose(cands, language="fr").id == "b"  # no French: English
    assert choose([p("c", "X", "s3", "1")]).id == "c"  # unpriced is still a printing
    assert choose([]) is None
    tied = [p("z", "X", "s9", "1", usd=1.0), p("y", "X", "s1", "2", usd=1.0), p("x", "X", "s1", "1", usd=1.0)]
    for _ in range(5):
        random.shuffle(tied)
        assert choose(tied).id == "x"  # the order a file was read in never changes the answer


def test_the_17_row_shape_of_a_real_export_loses_no_row():
    rows = ([CollectionEntry("Counterspell", set_code="MB1", collector_number=str(n)) for n in (3, 41, 1607)]
            + [CollectionEntry("Daxos, Blessed by the Sun", set_code=c, collector_number="258") for c in ("VTHB", "VXXX")]
            + [CollectionEntry("Lightning Bolt", set_code="PHED", collector_number="5")]
            + [CollectionEntry("Counterspell", set_code="PAGL", collector_number="77")]
            + [CollectionEntry("Nonexistent Marauder", set_code="FWB", collector_number="4")]
            + [CollectionEntry("Lightning Bolt", set_code="M11", collector_number="149")])
    found = [match(e) for e in rows]
    assert [m for _, m in found].count(None) == 1  # only the card no catalog has
    assert [m for _, m in found] == ["name_set"] * 3 + ["set_number", "name_number", "name", "name_set", None, "set_number"]


def test_derive_set_aliases_shows_which_set_a_code_stands_for():
    entries = [CollectionEntry("Daxos, Blessed by the Sun", set_code="VXXX", collector_number="258"),
               CollectionEntry("Daxos, Blessed by the Sun", set_code="VXXX", collector_number="7"),
               CollectionEntry("Lightning Bolt", set_code="QQQ", collector_number="149"),
               CollectionEntry("Lightning Bolt", set_code="QQQ", collector_number="117"),
               CollectionEntry("Lightning Bolt", set_code="M11", collector_number="149"),  # a set the catalog has
               CollectionEntry("Counterspell", set_code="NNN", collector_number="9999"),  # the name, never that number
               CollectionEntry("Nonexistent Marauder", set_code="NNN", collector_number="1")]
    proofs = {x.file_code: x for x in derive_set_aliases(entries, CATALOG)}
    assert sorted(proofs) == ["nnn", "qqq", "vxxx"]
    assert isinstance(proofs["vxxx"], AliasProof) and proofs["vxxx"].supported == "thb" and proofs["vxxx"].resolved == {"thb": 2}
    assert proofs["qqq"].supported is None and proofs["qqq"].resolved == {"m11": 1, "2xm": 1}  # two sets: not one alias
    assert (proofs["nnn"].name_only, proofs["nnn"].not_found, proofs["nnn"].supported) == (1, 1, None)
    # a code the caller knows the catalog has is never reported
    assert "vxxx" not in {x.file_code for x in derive_set_aliases(entries, CATALOG, known_codes=["vxxx"])}


def test_resolve_offline_uses_the_same_ladder_and_its_keys_keep_what_it_needs():
    def card(id, name, set_code, number, usd):
        return Card.from_json({"id": id, "name": name, "set": set_code, "collector_number": number,
                               "prices": {"usd": str(usd)}, "finishes": ["nonfoil"]})

    bulk = [card("cs-cmr", "Counterspell", "plst", "CMR-395", 1.2), card("cs-a25", "Counterspell", "a25", "50", 1.1),
            card("dax", "Daxos, Blessed by the Sun", "thb", "258", 0.4), card("other", "Other Card", "m11", "1", 1)]
    entries = [CollectionEntry("Counterspell", set_code="MB1", collector_number="1607"),
               CollectionEntry("Daxos, Blessed by the Sun", set_code="VXXX", collector_number="258"),
               CollectionEntry("Nope", set_code="FWB", collector_number="1")]
    got = [(r.card.id if r.card else None, r.method) for r in resolve_offline(entries, bulk)]
    assert got == [("cs-cmr", "name_set"), ("dax", "name_number"), (None, None)]  # the cheaper a25 is another set
    keys = index_keys(entries)
    assert ("set_number", "plst", "1607") in keys and ("name", "counterspell") in keys
    kept = [c for c in bulk if card_matches_keys(c, keys)]
    assert [c.id for c in kept] == ["cs-cmr", "cs-a25", "dax"]
    assert [(r.card.id if r.card else None, r.method) for r in resolve_offline(entries, kept)] == got


def test_the_alias_tables():
    assert normalize_set_code("GK2_ORZHOV") == "gk2" and "gk2_orzhov" in set_alias_map()
    # fallbacks are not rewritten (a row keeps the code it was written with): matching tries the fallback set second
    assert normalize_set_code("VTHB") == "vthb" and normalize_set_code("MB1") == "mb1"
    assert "vthb" not in set_alias_map() and "mb1" not in set_alias_map()
    assert set_code_fallbacks()["vthb"] == "thb"
    assert set_code_fallbacks()["pagl"] == "plst"
    copy = set_code_fallbacks()
    copy["mb1"] = "nope"
    assert fallback_set_code("mb1") == "plst"


# -- the review's cases: ambiguity, the name check on a fallback, precedence, the rule's edges ----------------------------


def test_name_and_number_in_several_sets_says_so_and_by_how_much():
    five = [p("a", "Test Old Border", "2ed", "76", usd=900.0), p("b", "Test Old Border", "3ed", "76", usd=60.0),
            p("c", "Test Old Border", "cei", "76", usd=30.0), p("d", "Test Old Border", "leb", "76", usd=4000.0),
            p("e", "Test Old Border", "ced", "76", usd=35.0), p("other", "Test Old Border", "4ed", "77", usd=1.0)]
    m = PrintingIndex(five).match(CollectionEntry("Test Old Border", set_code="FWB", collector_number="76"))
    assert (m.printing.id, m.method, m.candidates, m.lowest, m.highest) == ("c", "name_number", 5, 30.0, 4000.0)
    assert m.ambiguous and not m.exact
    one = PrintingIndex(five[:1]).match(CollectionEntry("Test Old Border", set_code="FWB", collector_number="76"))
    assert (one.method, one.candidates, one.ambiguous) == ("name_number", 1, False)
    exact = PrintingIndex(five).match(CollectionEntry("Test Old Border", set_code="2ed", collector_number="76"))
    assert exact.exact and not exact.ambiguous
    # the same through resolve_offline: the range is on the Resolution
    cards = [Card.from_json({"id": x.id, "name": x.name, "set": x.set_code, "collector_number": x.collector_number,
                             "prices": {"usd": str(x.usd)}}) for x in five]
    [res] = resolve_offline([CollectionEntry("Test Old Border", set_code="FWB", collector_number="76")], cards)
    assert (res.card.id, res.method, res.candidates, res.lowest, res.highest) == ("c", "name_number", 5, 30.0, 4000.0)


def test_a_fallback_code_never_ties_a_row_to_another_card_with_that_number():
    cat = [p("dax-258", "Daxos, Blessed by the Sun", "thb", "258", usd=0.4), p("other-259", "Some Other Card", "thb", "259", usd=1.0),
           p("dax-7", "Daxos, Blessed by the Sun", "thb", "7", usd=0.1)]
    wrong = CollectionEntry("Daxos, Blessed by the Sun", set_code="VTHB", collector_number="259")
    m = PrintingIndex(cat).match(wrong)
    assert m.printing.id == "dax-7" and m.method == "name_set"  # the card, not thb/259's card, and not called exact
    assert PrintingIndex(cat).match(wrong, fallback=False) == (None, None, 1, None, None)
    # a double-faced card is still its own printing under a face's name
    cat.append(p("fire", "Fire // Ice", "thb", "300", usd=0.3))
    assert PrintingIndex(cat).match(CollectionEntry("Ice", set_code="VTHB", collector_number="300")).method == "set_number"


def test_several_sets_sharing_a_number_are_chosen_by_language_then_price_then_order():
    cat = [p("z-en", "X", "zzz", "5", usd=2.0), p("a-en", "X", "aaa", "5", usd=2.0), p("m-en", "X", "mmm", "5", usd=1.5),
           p("m-de", "X", "mmm", "5", lang="de", usd=9.0), p("n-en", "X", "nnn", "5", usd=None)]
    idx = PrintingIndex(cat)
    assert idx.match(CollectionEntry("X", set_code="QQQ", collector_number="5")).printing.id == "m-en"  # cheapest English
    assert idx.match(CollectionEntry("X", set_code="QQQ", collector_number="5", language="de")).printing.id == "m-de"
    tied = PrintingIndex([c for c in cat if c.id in ("z-en", "a-en")] + [p("a-en2", "X", "aaa", "5", usd=2.0)])
    for _ in range(4):
        shuffled = list(tied.by_name_num[("x", "5")])
        random.shuffle(shuffled)
        assert PrintingIndex(shuffled).match(CollectionEntry("X", set_code="QQQ", collector_number="5")).printing.id == "a-en"


def test_a_catalog_holding_the_retired_code_and_its_set_keeps_the_precedence_of_the_steps():
    cat = [p("mb1-1607", "Counterspell", "mb1", "1607", usd=5.0), p("plst-1607", "Counterspell", "plst", "1607", usd=1.0),
           p("cs-cmr", "Counterspell", "plst", "CMR-395", usd=0.5)]
    entry = CollectionEntry("Counterspell", set_code="MB1", collector_number="1607")
    assert PrintingIndex(cat).match(entry).printing.id == "mb1-1607"  # the code as written first, though dearer
    assert PrintingIndex(cat[1:]).match(entry).printing.id == "plst-1607"  # then its fallback set with that number
    assert PrintingIndex(cat[2:]).match(entry) == PrintingIndex(cat[2:]).match(entry)
    only_name_set = PrintingIndex([cat[2], p("bolt", "Lightning Bolt", "m11", "1607", usd=1.0)]).match(entry)
    assert (only_name_set.printing.id, only_name_set.method) == ("cs-cmr", "name_set")  # not name_number: m11/1607 is another card
    # name + set comes before name + number: the same name with that number in another set loses to the set
    other = [p("cs-a25", "Counterspell", "a25", "1607", usd=0.1), cat[2]]
    assert PrintingIndex(other).match(entry).printing.id == "cs-cmr"


def test_a_token_or_memorabilia_printing_is_never_the_cheapest_pick_and_an_unpriced_finish_falls_back_to_a_price():
    cat = [p("wc", "Force of Will", "wc97", "jk28", usd=26.0)._replace(regular=False), p("dmr", "Force of Will", "dmr", "284", usd=56.0),
           p("all", "Force of Will", "all", "28", usd=90.0)]
    assert choose(cat).id == "dmr"  # a memorabilia printing is not what a person owns
    only_odd = [cat[0]]
    assert choose(only_odd).id == "wc"  # but a card with nothing else still has a printing
    # a foil row, none priced in foil: the cheapest in any finish, not the alphabetical set code (2ed $900 over cei $30)
    nofoil = [p("2ed", "X", "2ed", "76", usd=900.0), p("cei", "X", "cei", "76", usd=30.0)]
    assert choose(nofoil, finish=Finish.FOIL).id == "cei"
    got = pick(nofoil, finish=Finish.FOIL)
    assert (got.candidates, got.lowest, got.highest) == (2, 30.0, 900.0)


def test_a_card_from_scryfall_knows_whether_it_is_a_regular_printing():
    def card(**extra):
        return Card.from_json({"id": "x", "name": "N", "set": "s", "collector_number": "1", **extra})

    assert Printing.from_card(card()).regular
    for odd in ({"set_type": "memorabilia"}, {"layout": "art_series"}, {"digital": True}, {"oversized": True},
                {"layout": "token"}, {"set_type": "token"}):
        assert not Printing.from_card(card(**odd)).regular, odd


def test_a_resolution_still_unpacks_as_entry_card_method():
    bulk = [Card.from_json({"id": "a", "name": "Sol Ring", "set": "c21", "collector_number": "263"})]
    [res] = resolve_offline([CollectionEntry("Sol Ring", set_code="C21", collector_number="263")], bulk)
    entry, card, method = res
    assert (card.id, method, res[2], len(res), res.candidates) == ("a", "set_number", "set_number", 3, 1)


def test_the_tie_break_is_set_code_then_number_not_the_id_and_the_written_set_beats_its_fallback():
    # same price: the lowest set code wins although its id sorts last
    cat = [p("a-id", "X", "s9", "1", usd=1.0), p("b-id", "X", "s1", "9", usd=1.0), p("c-id", "X", "s1", "2", usd=1.0)]
    assert choose(cat).id == "c-id"
    # a name in both the set the file wrote and that code's fallback set: the written set first
    both = [p("in-mb1", "Counterspell", "mb1", "2", usd=9.0), p("in-plst", "Counterspell", "plst", "CMR-395", usd=1.0)]
    m = PrintingIndex(both).match(CollectionEntry("Counterspell", set_code="MB1", collector_number="1607"))
    assert (m.printing.id, m.method) == ("in-mb1", "name_set")
