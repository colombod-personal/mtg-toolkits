"""Join a collection with Scryfall data: oracle text, attributes and prices."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import CollectionEntry, Finish
from .scryfall import Card, ScryfallClient


@dataclass
class EnrichedEntry:
    entry: CollectionEntry
    card: Card | None
    method: str | None = None  # how the card was matched, see ScryfallClient.resolve_entries

    @property
    def unit_price(self) -> float | None:
        return self.card.prices.for_finish(self.entry.finish) if self.card else None

    @property
    def unit_price_eur(self) -> float | None:
        return self.card.prices.for_finish(self.entry.finish, "eur") if self.card else None

    @property
    def total_price(self) -> float | None:
        return None if self.unit_price is None else round(self.unit_price * self.entry.quantity, 2)


def enrich(entries: list[CollectionEntry], client: ScryfallClient, *, fix_finish: bool = True) -> list[EnrichedEntry]:
    """Resolve every entry against Scryfall (batched, 75 per request, with fallbacks).

    Matched entries get their Scryfall id filled in. With ``fix_finish``, an
    entry whose finish the printing doesn't come in (e.g. Dragon Shield's blank
    Printing on an etched-only card) takes the printing's only finish.
    """
    results = []
    for entry, card, method in client.resolve_entries(entries):
        if card:
            if not entry.scryfall_id and method in ("id", "set_number"):
                entry.scryfall_id = card.id
            finishes = [Finish(f) for f in card.finishes if f in Finish._value2member_map_]
            if fix_finish and len(finishes) == 1 and entry.finish not in finishes:
                entry.finish = finishes[0]
        results.append(EnrichedEntry(entry, card, method))
    return results


def summarize(enriched: Iterable[EnrichedEntry]) -> dict[str, float | int]:
    enriched = list(enriched)
    return {
        "entries": len(enriched),
        "cards": sum(e.entry.quantity for e in enriched),
        "unmatched": sum(1 for e in enriched if e.card is None),
        "matched_by_name_only": sum(1 for e in enriched if e.method == "name"),
        "unpriced": sum(1 for e in enriched if e.card and e.unit_price is None),
        "total_usd": round(sum(e.total_price or 0 for e in enriched), 2),
        "total_eur": round(sum((e.unit_price_eur or 0) * e.entry.quantity for e in enriched), 2),
    }


REPORT_COLUMNS = [
    "Folder", "Quantity", "Name", "Set", "Number", "Finish", "Condition", "Language",
    "Type", "Mana Cost", "CMC", "Colors", "Rarity", "Oracle Text",
    "USD", "EUR", "Total USD", "Purchase Price", "Scryfall ID", "Scryfall URL",
]


def write_report(enriched: Iterable[EnrichedEntry], path: str | Path) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(REPORT_COLUMNS)
        for item in enriched:
            e, c = item.entry, item.card
            w.writerow([
                e.folder or "", e.quantity, c.name if c else e.name,
                (c.set_code if c else e.set_code or "").upper(), c.collector_number if c else e.collector_number or "",
                e.finish.value, e.condition.value, e.language,
                c.type_line if c else "", c.mana_cost if c else "", c.cmc if c else "",
                "".join(c.colors) if c else "", c.rarity if c else "", c.oracle_text if c else "",
                item.unit_price if item.unit_price is not None else "",
                item.unit_price_eur if item.unit_price_eur is not None else "",
                item.total_price if item.total_price is not None else "",
                e.purchase_price if e.purchase_price is not None else "",
                c.id if c else "", c.scryfall_uri if c else "",
            ])
