"""Matching a collection row to a printing, with a stated rule for every step.

One ladder, used by the offline matcher (:func:`mtg_toolkits.scryfall.resolve_offline`, the Vault's daily sync) and by
anything that holds printings of its own (:class:`PrintingIndex`, the Vault's import preview), so a preview and the
sync that follow it say the same thing. (The online :meth:`~mtg_toolkits.scryfall.ScryfallClient.resolve_entries` is
the older, shorter ladder: ids, set + number, name + set, name.) The first step that finds a card wins; ``method``
says which:

1. ``"id"``: the Scryfall id in the file.
2. ``"set_number"``: set code and collector number, as :mod:`mtg_toolkits.normalize` reads them. A code the catalog
   does not hold as a set (:data:`~mtg_toolkits.normalize.SET_CODE_FALLBACKS`: ``VTHB`` -> ``THB``, ``MB1`` ->
   ``PLST``) is tried with its fallback set only after the code as written found nothing, and then only when the
   printing's name is the row's name (a fallback code is evidence about one set, not about every number in it).
3. ``"name_set"``: the card's name in that set (or its fallback set), when the number is not the catalog's.
4. ``"name_number"``: the card's name with that collector number in any set. This is what finds Dragon Shield's
   own variant sets (``VTHB/258`` is Theros Beyond Death 258) without a list of them.
5. ``"name"``: the card's name alone.

Steps 1 and 2 identify the printing the file names (:data:`EXACT_METHODS`). Steps 3 to 5 find the card, and the
printing is chosen by :func:`pick`, the one stated rule, because the file did not say which printing the person
owns. The answer says how sure that is: ``candidates`` is how many printings the rule chose among, and ``lowest``
and ``highest`` their prices, so a caller can say "between $X and $Y, shown at $X". Nothing is ever dropped: a row no
step finds is simply a row with no card.

The rule (:func:`pick`), among the candidates:

1. the printings in the row's language (else English, else any);
2. the regular printings (not a token, emblem, art-series card, memorabilia, digital or oversized printing: those
   are never the printing someone means, whatever they cost), unless there are none;
3. the lowest price in the row's finish; printings with no price in that finish come after, by their lowest price
   in any finish; printings with no price at all come last;
4. ties go to the lowest set code, collector number and id, so the answer never depends on the order a file was
   read in.

The cheapest is deliberate: when the file does not say which printing someone owns, a value that is too low is
a lesser mistake than one that is too high. It is still a guess, which is why ``candidates`` is returned.

Names are compared lower-cased, front face or any face; there is no folding of accents, quotes or spacing, so a name
written differently finds no card (never the wrong one).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, NamedTuple

from .models import CollectionEntry, Finish
from .normalize import fallback_set_code, normalize_collector_number, normalize_set_code

EXACT_METHODS = ("id", "set_number")  # the printing the file names; the other methods found the card, not the printing
# Printings that are never "the printing someone owns" of a card (the same lists the Vault keeps its catalog by).
IRREGULAR_LAYOUTS = frozenset({"token", "double_faced_token", "emblem", "art_series"})
IRREGULAR_SET_TYPES = frozenset({"memorabilia", "token"})


class Printing(NamedTuple):
    """The part of a printing matching needs. Build one from a Scryfall card with :meth:`from_card`, or from your own table."""

    id: str
    name: str  # as Scryfall names it: "Front // Back" for a double-faced card
    set_code: str
    collector_number: str
    lang: str = "en"
    usd: float | None = None
    usd_foil: float | None = None
    usd_etched: float | None = None
    faces: tuple = ()  # face names, when the card has them and ``name`` is not a joined name
    regular: bool = True  # False for a token, emblem, art-series, memorabilia, digital or oversized printing

    @classmethod
    def from_card(cls, card) -> "Printing":
        """From a :class:`mtg_toolkits.scryfall.Card`."""
        raw = card.raw
        faces = tuple(f.get("name") or "" for f in (raw.get("card_faces") or []))
        regular = not (raw.get("digital") or raw.get("oversized") or raw.get("layout") in IRREGULAR_LAYOUTS
                       or raw.get("set_type") in IRREGULAR_SET_TYPES)
        p = card.prices
        return cls(card.id, card.name, card.set_code, card.collector_number, card.lang, p.usd, p.usd_foil, p.usd_etched,
                   faces, regular)

    def price(self, finish: Finish) -> float | None:
        return {Finish.NONFOIL: self.usd, Finish.FOIL: self.usd_foil, Finish.ETCHED: self.usd_etched}.get(finish)

    def any_price(self) -> float | None:
        prices = [p for p in (self.usd, self.usd_foil, self.usd_etched) if p is not None]
        return min(prices) if prices else None


def front_face(name: str) -> str:
    return name.split(" // ")[0].strip()


def printing_names(p: Printing) -> set[str]:
    """Lower-cased full name, front face and every face name."""
    names = {p.name.lower(), front_face(p.name).lower()} | {n.lower() for n in p.faces}
    names |= {part.strip().lower() for part in p.name.split(" // ")}
    return names - {""}


class Pick(NamedTuple):
    """The printing the rule chose and how many it chose among (see :func:`pick`)."""

    printing: Printing
    candidates: int  # printings the rule chose among, after the language and the regular filter
    lowest: float | None  # their lowest and highest price in the row's finish (any finish when none has one)
    highest: float | None


def pick(candidates: Iterable[Printing], language: str | None = "en", finish: Finish = Finish.NONFOIL) -> Pick | None:
    """The stated rule for choosing one printing among several (see the module docstring), with how many it chose among."""
    found = list(candidates)
    if not found:
        return None
    pool = [c for c in found if c.lang == (language or "en")] or [c for c in found if c.lang == "en"] or found
    pool = [c for c in pool if c.regular] or pool

    def key(c: Printing):
        price, other = c.price(finish), c.any_price()
        return (price is None, price or 0.0, other is None, other or 0.0, c.set_code, c.collector_number, c.id)

    best = min(pool, key=key)
    in_finish = [c.price(finish) for c in pool if c.price(finish) is not None]
    priced = in_finish or [c.any_price() for c in pool if c.any_price() is not None]
    return Pick(best, len(pool), min(priced) if priced else None, max(priced) if priced else None)


def choose(candidates: Iterable[Printing], language: str | None = "en", finish: Finish = Finish.NONFOIL) -> Printing | None:
    """The printing :func:`pick` chooses, or None."""
    chosen = pick(candidates, language, finish)
    return chosen.printing if chosen else None


class Match(NamedTuple):
    printing: Printing | None
    method: str | None  # "id" | "set_number" | "name_set" | "name_number" | "name" | None
    candidates: int = 1  # how many printings the rule chose among (1 for a printing the file names)
    lowest: float | None = None  # their lowest and highest price in the row's finish
    highest: float | None = None

    @property
    def exact(self) -> bool:
        return self.method in EXACT_METHODS

    @property
    def ambiguous(self) -> bool:
        """The card was found but the file does not say which of several printings it is."""
        return self.method is not None and not self.exact and self.candidates > 1


class PrintingIndex:
    """Printings by id, set and number, name and set, name and number, and name."""

    def __init__(self, printings: Iterable[Printing]):
        self.by_id: dict[str, Printing] = {}
        self.by_set_num: dict[tuple, list[Printing]] = defaultdict(list)
        self.by_name_set: dict[tuple, list[Printing]] = defaultdict(list)
        self.by_name_num: dict[tuple, list[Printing]] = defaultdict(list)
        self.by_name: dict[str, list[Printing]] = defaultdict(list)
        self.set_codes: set[str] = set()
        for p in printings:
            code, number = normalize_set_code(p.set_code) or "", normalize_collector_number(p.collector_number) or ""
            self.by_id[p.id] = p
            self.set_codes.add(code)
            self.by_set_num[(code, number)].append(p)
            for n in printing_names(p):
                self.by_name_set[(n, code)].append(p)
                self.by_name_num[(n, number)].append(p)
                self.by_name[n].append(p)

    def match(self, entry: CollectionEntry, *, fallback: bool = True) -> Match:
        """The printing for a row and how it was found. ``fallback=False`` stops after the steps that identify a printing."""
        language, finish = entry.language or "en", entry.finish

        def found(candidates, method: str) -> Match | None:
            chosen = pick(candidates, language, finish)
            return Match(chosen.printing, method, chosen.candidates, chosen.lowest, chosen.highest) if chosen else None

        if entry.scryfall_id and entry.scryfall_id in self.by_id:
            return Match(self.by_id[entry.scryfall_id], "id")
        code, number = normalize_set_code(entry.set_code), normalize_collector_number(entry.collector_number)
        if code and number and (m := found(self.by_set_num.get((code, number), ()), "set_number")):
            return m
        row_names = {n for n in ((entry.name or "").strip().lower(), front_face(entry.name or "").lower()) if n}
        merged = fallback_set_code(code)
        if merged and number:
            # a fallback code is evidence about a set, not about every number in it: the printing must be the row's card
            named = [p for p in self.by_set_num.get((merged, number), ()) if not row_names or row_names & printing_names(p)]
            if m := found(named, "set_number"):
                return m
        if not fallback:
            return Match(None, None)
        name = front_face(entry.name or "").lower()
        if not name:
            return Match(None, None)
        for set_code in (code, merged):
            if set_code and (m := found(self.by_name_set.get((name, set_code), ()), "name_set")):
                return m
        if number and (m := found(self.by_name_num.get((name, number), ()), "name_number")):
            return m
        return found(self.by_name.get(name, ()), "name") or Match(None, None)


def index_keys(entries: Iterable[CollectionEntry], *, fallback: bool = True) -> set[tuple]:
    """The lookup keys :meth:`PrintingIndex.match` can use for ``entries``: ``("id", id)``,
    ``("set_number", set, number)`` (also with the fallback set) and ``("name", lower-case name)``."""
    keys: set[tuple] = set()
    for e in entries:
        if e.scryfall_id:
            keys.add(("id", e.scryfall_id))
        code, number = normalize_set_code(e.set_code), normalize_collector_number(e.collector_number)
        if code and number:
            keys.add(("set_number", code, number))
        merged = fallback_set_code(code)
        if merged and number:
            keys.add(("set_number", merged, number))
        if fallback:
            if (name := front_face(e.name or "").lower()):
                keys.add(("name", name))
    return keys


# -- finding which set code a file's own code stands for ------------------------------------------------------------


@dataclass
class AliasProof:
    """What the rows of a file say about one set code the catalog does not know."""

    file_code: str
    rows: int  # rows of the file with this code
    resolved: dict[str, int]  # catalog set code -> rows whose name and collector number are that set's printing
    name_only: int  # rows whose name is in the catalog but not with that number anywhere
    not_found: int  # rows whose name is not in the catalog at all
    examples: list[tuple]  # up to three (name, number, catalog set) rows that back the proof

    @property
    def supported(self) -> str | None:
        """The catalog code every resolved row agrees on, when at least one row resolved and none points elsewhere."""
        return next(iter(self.resolved)) if len(self.resolved) == 1 else None


def derive_set_aliases(entries: Iterable[CollectionEntry], printings: Iterable[Printing],
                       known_codes: Iterable[str] | None = None) -> list[AliasProof]:
    """For every set code in ``entries`` that no printing carries, which catalog set the rows' own names and collector
    numbers say it is: the table to review before adding a code to :data:`~mtg_toolkits.normalize.SET_ALIASES` or
    :data:`~mtg_toolkits.normalize.SET_CODE_FALLBACKS`.

    ``printings`` should hold every printing of the names in the file. ``known_codes`` is the catalog's list of set
    codes (Scryfall's ``/sets``); without it a code is unknown when none of ``printings`` has it. A code that is
    already in :data:`~mtg_toolkits.normalize.SET_CODE_FALLBACKS` is still reported, so its mapping can be checked.
    """
    index = PrintingIndex(printings)
    known = {normalize_set_code(c) for c in (known_codes if known_codes is not None else index.set_codes)}
    rows: dict[str, list[CollectionEntry]] = defaultdict(list)
    for e in entries:
        code = normalize_set_code(e.set_code)
        if code and code not in known:
            rows[(e.set_code or "").strip().lower()].append(e)
    proofs = []
    for file_code, group in sorted(rows.items()):
        resolved: Counter = Counter()
        examples, name_only, not_found = [], 0, 0
        for e in group:
            name, number = front_face(e.name or "").lower(), normalize_collector_number(e.collector_number)
            hits = {p.set_code for p in index.by_name_num.get((name, number or ""), ())} if number else set()
            if len(hits) == 1:
                (code,) = hits
                resolved[code] += 1
                if len(examples) < 3:
                    examples.append((e.name, e.collector_number, code))
            elif name in index.by_name:
                name_only += 1
            else:
                not_found += 1
        proofs.append(AliasProof(file_code, len(group), dict(resolved), name_only, not_found, examples))
    return proofs
