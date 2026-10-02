"""Compare collection snapshots and work with the differences ("deltas").

Typical uses::

    from mtg_toolkits import delta, dragonshield

    old = dragonshield.read("export-2026-08.csv")
    new = dragonshield.read("export-2026-09.csv")
    d = delta.diff(old, new)
    print(d.summary())                      # {'added': 12, 'removed': 3, ...}
    dragonshield.write(d.gains(), "to-import.csv")   # only what's new

    # What am I missing for this Archidekt deck?
    need = delta.shortfall(deck.to_entries(), owned=new)

Entries are matched on a *key* built from selected fields. Pick how strict the
match is with ``by``:

* :data:`BY_CARD` -- card name only ("do I own a Sol Ring at all?")
* :data:`BY_PRINTING` -- name + set + collector number + finish (default)
* :data:`BY_COPY` -- printing + condition + language

Pass ``folders=True`` to also treat the folder/binder as part of the key, so
moving cards between folders shows up as a removal plus an addition.

Values are normalised before comparing: names are case-folded and reduced to
the front face ("Delver of Secrets // Insectile Aberration" matches "Delver of
Secrets"), set codes and collector numbers are normalised the way the Scryfall
matcher does it (:mod:`mtg_toolkits.normalize`: lower-cased, Dragon Shield set
aliases applied, ``*`` read as ``★``, leading zeros dropped). Rows sharing a key are summed, so split stacks compare correctly.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

from .models import CollectionEntry
from .normalize import normalize_collector_number, normalize_set_code

BY_CARD: tuple[str, ...] = ("name",)
BY_PRINTING: tuple[str, ...] = ("name", "set_code", "collector_number", "finish")
BY_COPY: tuple[str, ...] = BY_PRINTING + ("condition", "language")


def _name(e: CollectionEntry) -> str:
    return e.name.split(" // ")[0].strip().casefold()


def _number(e: CollectionEntry) -> str:
    return normalize_collector_number(e.collector_number) or ""


_NORMALISERS: dict[str, Callable[[CollectionEntry], str]] = {
    "name": _name,
    "set_code": lambda e: normalize_set_code(e.set_code) or "",
    "collector_number": _number,
    "finish": lambda e: e.finish.value,
    "condition": lambda e: e.condition.value,
    "language": lambda e: (e.language or "en").lower(),
    "folder": lambda e: (e.folder or "").strip(),
    "scryfall_id": lambda e: (e.scryfall_id or "").lower(),
}

Key = tuple[str, ...]


def _fields(by: Iterable[str], folders: bool) -> tuple[str, ...]:
    fields = tuple(by) + (("folder",) if folders and "folder" not in by else ())
    unknown = [f for f in fields if f not in _NORMALISERS]
    if unknown:
        raise ValueError(f"Cannot match on {unknown}; choose from {sorted(_NORMALISERS)}")
    return fields


def key_of(entry: CollectionEntry, by: Iterable[str] = BY_PRINTING, *, folders: bool = False) -> Key:
    """The normalised matching key for ``entry``."""
    return tuple(_NORMALISERS[f](entry) for f in _fields(by, folders))


def aggregate(
    entries: Iterable[CollectionEntry], by: Iterable[str] = BY_PRINTING, *, folders: bool = False
) -> dict[Key, CollectionEntry]:
    """Merge rows that share a key, summing ``quantity`` and ``trade_quantity``.

    The first row seen for a key supplies the other fields, and a missing
    Scryfall id is filled from later rows.
    """
    fields = _fields(by, folders)
    merged: dict[Key, CollectionEntry] = {}
    for e in entries:
        k = tuple(_NORMALISERS[f](e) for f in fields)
        if k not in merged:
            merged[k] = replace(e, source_prices=dict(e.source_prices), extra=dict(e.extra))
            continue
        m = merged[k]
        m.quantity += e.quantity
        m.trade_quantity += e.trade_quantity
        m.scryfall_id = m.scryfall_id or e.scryfall_id
    return merged


@dataclass
class DeltaLine:
    """How the quantity of one key changed between two snapshots."""

    key: Key
    entry: CollectionEntry  # representative row (from the new side when present)
    old: int
    new: int

    @property
    def delta(self) -> int:
        return self.new - self.old

    @property
    def status(self) -> str:
        if self.old == self.new:
            return "unchanged"
        if self.old <= 0:
            return "added"
        if self.new <= 0:
            return "removed"
        return "increased" if self.new > self.old else "decreased"

    def as_entry(self, quantity: int | None = None) -> CollectionEntry:
        """A copy of the representative entry with ``quantity`` (default: ``abs(delta)``)."""
        return replace(self.entry, quantity=abs(self.delta) if quantity is None else quantity)


@dataclass
class CollectionDiff:
    lines: list[DeltaLine]
    fields: tuple[str, ...]

    def _with(self, *statuses: str) -> list[DeltaLine]:
        return [line for line in self.lines if line.status in statuses]

    @property
    def added(self) -> list[DeltaLine]:
        return self._with("added")

    @property
    def removed(self) -> list[DeltaLine]:
        return self._with("removed")

    @property
    def increased(self) -> list[DeltaLine]:
        return self._with("increased")

    @property
    def decreased(self) -> list[DeltaLine]:
        return self._with("decreased")

    @property
    def unchanged(self) -> list[DeltaLine]:
        return self._with("unchanged")

    @property
    def changes(self) -> list[DeltaLine]:
        return [line for line in self.lines if line.delta]

    def __bool__(self) -> bool:
        return any(line.delta for line in self.lines)

    def gains(self) -> list[CollectionEntry]:
        """Entries for everything that went up, with quantity = copies gained."""
        return [line.as_entry() for line in self.lines if line.delta > 0]

    def losses(self) -> list[CollectionEntry]:
        """Entries for everything that went down, with quantity = copies lost."""
        return [line.as_entry() for line in self.lines if line.delta < 0]

    def apply(self, base: Iterable[CollectionEntry]) -> list[CollectionEntry]:
        """Apply this diff to ``base`` and return the resulting (aggregated) entries.

        ``diff(old, new).apply(old)`` reproduces ``new`` at the diff's key
        granularity. Keys that drop to zero are left out.
        """
        result = aggregate(base, self.fields)
        for line in self.lines:
            if not line.delta:
                continue
            if line.key in result:
                result[line.key].quantity += line.delta
            elif line.delta > 0:
                result[line.key] = line.as_entry(line.delta)
        return [e for e in result.values() if e.quantity > 0]

    def summary(self) -> dict[str, int]:
        return {
            "added": len(self.added),
            "removed": len(self.removed),
            "increased": len(self.increased),
            "decreased": len(self.decreased),
            "unchanged": len(self.unchanged),
            "copies_in": sum(line.delta for line in self.lines if line.delta > 0),
            "copies_out": -sum(line.delta for line in self.lines if line.delta < 0),
        }


def diff(
    old: Iterable[CollectionEntry],
    new: Iterable[CollectionEntry],
    by: Iterable[str] = BY_PRINTING,
    *,
    folders: bool = False,
) -> CollectionDiff:
    """Compare two snapshots. Lines are sorted by status, then key.

    Line keys are laid out like :func:`key_of` (``by`` order, then the folder if ``folders``).
    """
    fields = _fields(by, folders)
    before = aggregate(old, fields)
    after = aggregate(new, fields)
    lines = []
    for k in before.keys() | after.keys():
        rep = after.get(k) or before[k]
        if k in after and k in before and not rep.scryfall_id:
            rep = replace(rep, scryfall_id=before[k].scryfall_id)
        lines.append(DeltaLine(k, rep, before[k].quantity if k in before else 0, after[k].quantity if k in after else 0))
    order = {"added": 0, "increased": 1, "decreased": 2, "removed": 3, "unchanged": 4}
    lines.sort(key=lambda line: (order[line.status], line.key))
    return CollectionDiff(lines, fields)


def shortfall(
    needed: Iterable[CollectionEntry], owned: Iterable[CollectionEntry], by: Iterable[str] = BY_CARD
) -> list[CollectionEntry]:
    """What is in ``needed`` (e.g. a deck) but not covered by ``owned``.

    Matches on card name by default, so any printing you own counts.
    """
    return diff(owned, needed, by).gains()


@dataclass
class CoverageLine:
    """How much of one needed card a collection covers."""

    entry: CollectionEntry  # representative needed entry, quantity = copies needed
    have: int

    @property
    def need(self) -> int:
        return self.entry.quantity

    @property
    def missing(self) -> int:
        return max(0, self.need - self.have)

    @property
    def status(self) -> str:
        if self.have >= self.need:
            return "owned"
        return "partial" if self.have > 0 else "missing"


def coverage(
    needed: Iterable[CollectionEntry], owned: Iterable[CollectionEntry], by: Iterable[str] = BY_CARD
) -> list[CoverageLine]:
    """Per-card coverage of ``needed`` (e.g. a decklist) by ``owned``.

    Each line reports ``have``/``need``/``missing`` and a status of
    ``"owned"``, ``"partial"`` or ``"missing"``. Matches on card name by default,
    so any printing you own counts. Multiply ``missing`` by a price from
    :mod:`mtg_toolkits.enrich` to get the cost to complete.
    """
    fields = _fields(by, False)
    have = aggregate(owned, fields)
    return [
        CoverageLine(entry, have[k].quantity if k in have else 0)
        for k, entry in aggregate(needed, fields).items()
    ]


DIFF_CSV_COLUMNS = [
    "Change", "Delta", "Old Quantity", "New Quantity", "Name", "Set Code", "Collector Number",
    "Finish", "Condition", "Language", "Folder", "Scryfall ID",
]


def write_csv(d: CollectionDiff, path: str | Path, *, include_unchanged: bool = False) -> int:
    """Write a human-readable change report. Returns the number of rows written."""
    rows = 0
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(DIFF_CSV_COLUMNS)
        for line in d.lines:
            if not include_unchanged and not line.delta:
                continue
            e = line.entry
            w.writerow([
                line.status, f"{line.delta:+d}", line.old, line.new, e.name, e.set_code or "",
                e.collector_number or "", e.finish.value, e.condition.value, e.language,
                e.folder or "", e.scryfall_id or "",
            ])
            rows += 1
    return rows
