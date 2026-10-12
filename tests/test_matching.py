"""The matching ladder (mtg_toolkits.matching): id, set + number (with a fallback set), name + set,
name + collector number, name; and the stated rule for picking a printing. Synthetic printings only."""

import random

from mtg_toolkits.matching import EXACT_METHODS, AliasProof, Printing, PrintingIndex, choose, derive_set_aliases, index_keys
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
