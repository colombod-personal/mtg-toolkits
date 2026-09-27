"""Client for Archidekt's (unofficial, undocumented) JSON API.

Archidekt has no published API docs. The maintainers say the read API is
"open and public" but may change without notice, and ask that public use of
the data links back to Archidekt. Known endpoints:

* ``GET /api/decks/{id}/`` -- full public deck, including every card's
  Scryfall id (``card.uid``), edition, finish (``modifier``) and categories.
* ``GET /api/decks/v3/?name=...&ownerUsername=...&orderBy=-updatedAt&page=N``
  -- deck search (pages of ~50-60 results, ``next`` link for pagination).

Private decks return 404 without authentication. Be gentle: there is no
published rate limit, so we default to one request per second.

Collections are not exposed through a stable public endpoint; use Archidekt's
CSV collection import/export (see :func:`write_collection_csv`).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from .http import ApiError, BaseClient
from .models import CollectionEntry, Condition, Finish

# Categories Archidekt excludes from the main deck by default.
NON_DECK_CATEGORIES = {"Maybeboard", "Sideboard"}

MODIFIER_TO_FINISH = {"normal": Finish.NONFOIL, "foil": Finish.FOIL, "etched": Finish.ETCHED}


@dataclass
class DeckCard:
    name: str
    quantity: int
    categories: list[str]
    finish: Finish
    scryfall_id: str | None
    set_code: str | None
    set_name: str | None
    collector_number: str | None
    prices: dict[str, float]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "DeckCard":
        card = data.get("card") or {}
        oracle = card.get("oracleCard") or {}
        edition = card.get("edition") or {}
        return cls(
            name=oracle.get("name") or card.get("displayName") or card.get("name", ""),
            quantity=int(data.get("quantity", 1)),
            categories=list(data.get("categories") or []),
            finish=MODIFIER_TO_FINISH.get(str(data.get("modifier", "Normal")).lower(), Finish.NONFOIL),
            scryfall_id=card.get("uid"),
            set_code=edition.get("editioncode"),
            set_name=edition.get("editionname"),
            collector_number=card.get("collectorNumber"),
            prices={k: float(v) for k, v in (card.get("prices") or {}).items() if isinstance(v, (int, float)) and v},
            raw=data,
        )


@dataclass
class Deck:
    id: int
    name: str
    format: int | None
    owner: str | None
    description: str | None
    cards: list[DeckCard]
    categories: list[dict[str, Any]]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Deck":
        owner = data.get("owner") or {}
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            format=data.get("deckFormat"),
            owner=owner.get("username") if isinstance(owner, dict) else owner,
            description=data.get("description"),
            cards=[DeckCard.from_json(c) for c in data.get("cards", []) if not c.get("deletedAt")],
            categories=data.get("categories", []),
            raw=data,
        )

    def _excluded(self) -> set[str]:
        excluded = {c["name"] for c in self.categories if c.get("includedInDeck") is False}
        return excluded or set(NON_DECK_CATEGORIES)

    def mainboard(self) -> list[DeckCard]:
        excluded = self._excluded()
        return [c for c in self.cards if not (c.categories and c.categories[0] in excluded)]

    def to_text(self, include_excluded: bool = False) -> str:
        """Plain ``N Card Name (SET) 123`` list, as accepted by most deck sites."""
        cards = self.cards if include_excluded else self.mainboard()
        lines = []
        for c in sorted(cards, key=lambda c: c.name):
            suffix = f" ({c.set_code.upper()}) {c.collector_number}" if c.set_code and c.collector_number else ""
            foil = " *F*" if c.finish is Finish.FOIL else (" *E*" if c.finish is Finish.ETCHED else "")
            lines.append(f"{c.quantity} {c.name}{suffix}{foil}")
        return "\n".join(lines)

    def to_entries(self) -> list[CollectionEntry]:
        return [
            CollectionEntry(
                name=c.name,
                quantity=c.quantity,
                set_code=c.set_code,
                set_name=c.set_name,
                collector_number=c.collector_number,
                finish=c.finish,
                scryfall_id=c.scryfall_id,
                folder=self.name,
            )
            for c in self.cards
        ]


class ArchidektClient(BaseClient):
    base_url = "https://archidekt.com/api"
    min_interval = 1.0

    def get_deck(self, deck_id: int | str) -> Deck:
        resp = self._request("GET", f"/decks/{deck_id}/")
        if resp.status_code == 404:
            raise ApiError(404, f"Deck {deck_id} not found or private")
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        return Deck.from_json(resp.json())

    def search_decks(self, *, limit: int | None = None, **params: Any) -> Iterator[dict[str, Any]]:
        """Search public decks. Common params: ``name``, ``ownerUsername``,
        ``commanderName``, ``cardName``, ``deckFormat`` (int), ``orderBy``.
        Yields the raw summary dicts."""
        url: str | None = "/decks/v3/"
        query: dict[str, Any] | None = params
        count = 0
        while url:
            resp = self._request("GET", url, params=query)
            if resp.status_code >= 400:
                raise ApiError(resp.status_code, resp.text)
            page = resp.json()
            for item in page.get("results", []):
                yield item
                count += 1
                if limit is not None and count >= limit:
                    return
            # "next" already carries the query; passing params would replace it.
            url, query = page.get("next"), None


# -- Archidekt collection CSV ---------------------------------------------------------

ARCHIDEKT_CSV_COLUMNS = [
    "Quantity", "Name", "Finish", "Condition", "Date Added", "Language",
    "Purchase Price", "Tags", "Edition Name", "Edition Code", "Collector Number", "Scryfall ID",
]

_CONDITION_TO_ARCHIDEKT = {
    Condition.MINT: "NM", Condition.NEAR_MINT: "NM", Condition.EXCELLENT: "LP",
    Condition.GOOD: "LP", Condition.LIGHT_PLAYED: "MP", Condition.PLAYED: "HP", Condition.POOR: "D",
}
_LANG_TO_ARCHIDEKT = {"ja": "JP", "ko": "KR", "zhs": "CS", "zht": "CT"}
_FINISH_TO_ARCHIDEKT = {Finish.NONFOIL: "Normal", Finish.FOIL: "Foil", Finish.ETCHED: "Etched"}


def write_collection_csv(entries: Iterable[CollectionEntry], path: str | Path, *, folder_as_tag: bool = True) -> int:
    """Write entries in a CSV layout Archidekt's collection importer can map.

    In the importer, map the columns by header name. Returns number of rows written.
    """
    rows = 0
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(ARCHIDEKT_CSV_COLUMNS)
        for e in entries:
            writer.writerow([
                e.quantity,
                e.name,
                _FINISH_TO_ARCHIDEKT[e.finish],
                _CONDITION_TO_ARCHIDEKT[e.condition],
                e.purchase_date.isoformat() if e.purchase_date else "",
                _LANG_TO_ARCHIDEKT.get(e.language, e.language.upper()),
                f"{e.purchase_price:.2f}" if e.purchase_price is not None else "",
                e.folder if folder_as_tag and e.folder else "",
                e.set_name or "",
                (e.set_code or "").lower(),
                e.collector_number or "",
                e.scryfall_id or "",
            ])
            rows += 1
    return rows
