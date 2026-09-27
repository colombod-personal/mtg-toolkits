"""Client for the Scryfall REST API (https://scryfall.com/docs/api).

Scryfall is the primary source for card text, attributes, images and (daily)
prices. Usage rules worth knowing:

* Every request must send a descriptive ``User-Agent`` and an ``Accept`` header.
* Keep traffic under 10 requests/second (50-100 ms between calls); the
  ``/cards/collection``, ``/cards/search``, ``/cards/named`` and ``/cards/random``
  endpoints are throttled harder, so we space those 500 ms apart.
* A 429 response locks the client out for 30 seconds; repeated overload can
  get the application banned. We back off for 30 s on 429.
* Prices are refreshed roughly once a day and "should be considered dangerously
  stale after 24 hours". For bulk work, use the bulk-data files (gzipped JSON
  Lines, hosted on ``data.scryfall.io`` without rate limits) instead of
  hammering the API.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from .http import ApiError, BaseClient, Throttle
from .models import CollectionEntry, Finish

COLLECTION_BATCH_SIZE = 75  # Scryfall's hard maximum per /cards/collection request


@dataclass
class CardPrices:
    usd: float | None = None
    usd_foil: float | None = None
    usd_etched: float | None = None
    eur: float | None = None
    eur_foil: float | None = None
    eur_etched: float | None = None
    tix: float | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> "CardPrices":
        data = data or {}
        return cls(**{k: float(data[k]) if data.get(k) else None for k in cls.__dataclass_fields__})

    def for_finish(self, finish: Finish, currency: str = "usd") -> float | None:
        suffix = {Finish.NONFOIL: "", Finish.FOIL: "_foil", Finish.ETCHED: "_etched"}[finish]
        return getattr(self, currency + suffix, None)


@dataclass
class Card:
    """The commonly used subset of a Scryfall card object. ``raw`` keeps everything."""

    id: str
    oracle_id: str | None
    name: str
    set_code: str
    set_name: str
    collector_number: str
    lang: str
    rarity: str
    layout: str
    mana_cost: str | None
    cmc: float | None
    type_line: str | None
    oracle_text: str | None
    power: str | None
    toughness: str | None
    loyalty: str | None
    colors: list[str]
    color_identity: list[str]
    keywords: list[str]
    legalities: dict[str, str]
    finishes: list[str]
    prices: CardPrices
    image_uris: dict[str, str]
    scryfall_uri: str | None
    purchase_uris: dict[str, str]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Card":
        faces = data.get("card_faces") or []

        def pick(key: str, joiner: str = " // "):
            if data.get(key) is not None:
                return data[key]
            values = [f[key] for f in faces if f.get(key)]
            return joiner.join(values) if values else None

        image_uris = data.get("image_uris") or (faces[0].get("image_uris") if faces else None) or {}
        return cls(
            id=data["id"],
            oracle_id=data.get("oracle_id"),
            name=data["name"],
            set_code=data.get("set", ""),
            set_name=data.get("set_name", ""),
            collector_number=data.get("collector_number", ""),
            lang=data.get("lang", "en"),
            rarity=data.get("rarity", ""),
            layout=data.get("layout", ""),
            mana_cost=pick("mana_cost"),
            cmc=data.get("cmc"),
            type_line=pick("type_line"),
            oracle_text=pick("oracle_text", "\n//\n"),
            power=pick("power"),
            toughness=pick("toughness"),
            loyalty=pick("loyalty"),
            colors=data.get("colors") or sorted({c for f in faces for c in f.get("colors", [])}),
            color_identity=data.get("color_identity", []),
            keywords=data.get("keywords", []),
            legalities=data.get("legalities", {}),
            finishes=data.get("finishes", []),
            prices=CardPrices.from_json(data.get("prices")),
            image_uris=image_uris,
            scryfall_uri=data.get("scryfall_uri"),
            purchase_uris=data.get("purchase_uris", {}),
            raw=data,
        )


class ScryfallClient(BaseClient):
    base_url = "https://api.scryfall.com"
    min_interval = 0.1

    def __init__(self, *args, slow_interval: float = 0.5, **kwargs):
        super().__init__(*args, **kwargs)
        self._slow = Throttle(slow_interval)

    # -- low level ---------------------------------------------------------------
    def _get_json(self, path: str, *, slow: bool = False, **kwargs) -> dict[str, Any]:
        resp = self._request("GET", path, throttle=self._slow if slow else None, **kwargs)
        return self._json(resp)

    @staticmethod
    def _json(resp) -> dict[str, Any]:
        data = resp.json()
        if resp.status_code >= 400 or data.get("object") == "error":
            raise ApiError(resp.status_code, data.get("details", resp.text), data)
        return data

    # -- cards -------------------------------------------------------------------
    def card(self, card_id: str) -> Card:
        """Fetch a card by its Scryfall id."""
        return Card.from_json(self._get_json(f"/cards/{card_id}"))

    def card_by_set_number(self, set_code: str, collector_number: str, lang: str | None = None) -> Card:
        path = f"/cards/{set_code.lower()}/{collector_number}" + (f"/{lang}" if lang else "")
        return Card.from_json(self._get_json(path))

    def named(self, name: str, *, fuzzy: bool = False, set_code: str | None = None) -> Card:
        """Look a card up by exact (or fuzzy) name."""
        params = {"fuzzy" if fuzzy else "exact": name}
        if set_code:
            params["set"] = set_code.lower()
        return Card.from_json(self._get_json("/cards/named", slow=True, params=params))

    def search(self, query: str, *, unique: str = "cards", order: str = "name", limit: int | None = None) -> Iterator[Card]:
        """Iterate over results of a full-text Scryfall search (https://scryfall.com/docs/syntax).

        Transparently follows pagination. A query with no matches yields nothing.
        """
        params: dict[str, Any] | None = {"q": query, "unique": unique, "order": order}
        url = "/cards/search"
        count = 0
        while url:
            resp = self._request("GET", url, throttle=self._slow, params=params)
            if resp.status_code == 404:
                return
            page = self._json(resp)
            for item in page.get("data", []):
                yield Card.from_json(item)
                count += 1
                if limit is not None and count >= limit:
                    return
            url, params = (page.get("next_page") if page.get("has_more") else None), None

    def collection(self, identifiers: Iterable[dict[str, str]]) -> tuple[list[Card], list[dict[str, str]]]:
        """Resolve many cards at once via ``POST /cards/collection``.

        ``identifiers`` are dicts such as ``{"id": ...}``, ``{"name": ...}``,
        ``{"set": "neo", "collector_number": "1"}``. Batches of 75 are sent
        automatically. Returns ``(found_cards, not_found_identifiers)``.
        """
        ids = list(identifiers)
        found: list[Card] = []
        missing: list[dict[str, str]] = []
        for i in range(0, len(ids), COLLECTION_BATCH_SIZE):
            batch = ids[i : i + COLLECTION_BATCH_SIZE]
            resp = self._request("POST", "/cards/collection", throttle=self._slow, json={"identifiers": batch})
            data = self._json(resp)
            found.extend(Card.from_json(c) for c in data.get("data", []))
            missing.extend(data.get("not_found", []))
        return found, missing

    def autocomplete(self, text: str) -> list[str]:
        return self._get_json("/cards/autocomplete", params={"q": text}).get("data", [])

    # -- sets / bulk data -------------------------------------------------------
    def sets(self) -> list[dict[str, Any]]:
        return self._get_json("/sets").get("data", [])

    def bulk_data(self) -> list[dict[str, Any]]:
        """List available bulk files (``oracle_cards``, ``default_cards``, ``all_cards``, ...)."""
        return self._get_json("/bulk-data").get("data", [])

    def download_bulk(self, bulk_type: str, dest: str | Path) -> Path:
        """Stream a bulk-data file (e.g. ``"default_cards"``) to ``dest``.

        Files are gzipped JSON Lines (``.jsonl.gz``); read them with :func:`iter_bulk_file`.
        """
        entry = next((b for b in self.bulk_data() if b["type"] == bulk_type), None)
        if entry is None:
            raise ValueError(f"Unknown bulk data type: {bulk_type}")
        uri = entry.get("jsonl_download_uri") or entry["download_uri"]
        dest = Path(dest)
        with self._client.stream("GET", uri) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
        return dest

    # -- helpers ----------------------------------------------------------------
    def resolve_entries(self, entries: list[CollectionEntry]) -> list[tuple[CollectionEntry, Card | None]]:
        """Match collection entries to Scryfall cards (one batched lookup)."""
        identifiers = [e.scryfall_identifier() for e in entries]
        cards, _ = self.collection(identifiers)
        by_id = {c.id: c for c in cards}
        by_set_num = {(c.set_code, c.collector_number): c for c in cards}
        by_name_set = {(c.name.lower(), c.set_code): c for c in cards}
        by_name = {}
        for c in cards:
            by_name.setdefault(c.name.lower(), c)
            for face in c.raw.get("card_faces", []):  # "Delver of Secrets" matches the DFC
                by_name.setdefault(face.get("name", "").lower(), c)

        results = []
        for entry, ident in zip(entries, identifiers):
            if "id" in ident:
                card = by_id.get(ident["id"])
            elif "collector_number" in ident:
                card = by_set_num.get((ident["set"], ident["collector_number"]))
            elif "set" in ident:
                card = by_name_set.get((ident["name"].lower(), ident["set"])) or by_name.get(ident["name"].lower())
            else:
                card = by_name.get(ident["name"].lower())
            results.append((entry, card))
        return results


def iter_bulk_file(path: str | Path) -> Iterator[dict[str, Any]]:
    """Stream objects from a downloaded bulk file without loading it all into memory.

    Handles the current ``.jsonl.gz`` format and plain ``.jsonl``. For card
    files, wrap each object with :meth:`Card.from_json`.
    """
    path = Path(path)
    with path.open("rb") as raw:
        gzipped = raw.read(2) == b"\x1f\x8b"
    opener = gzip.open if gzipped else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
