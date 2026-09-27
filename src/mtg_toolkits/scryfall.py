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
from typing import Any, Iterable, Iterator, NamedTuple

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
    def resolve_entries(self, entries: list[CollectionEntry], *, fallback: bool = True) -> list[Resolution]:
        """Match collection entries to Scryfall cards using batched lookups.

        Each distinct identifier is sent once. When ``fallback`` is on, entries
        that don't resolve are retried by name + set, then by name alone. The
        ``method`` on each result says which step matched (``"id"``,
        ``"set_number"``, ``"name_set"``, ``"name"``) or is ``None`` when nothing did.
        """
        results: list[Resolution | None] = [None] * len(entries)
        pending = list(range(len(entries)))
        steps = [("primary", lambda e: e.scryfall_identifier())]
        if fallback:
            steps += [
                ("name_set", lambda e: {"name": _front(e.name), "set": e.set_code.lower()} if e.set_code else None),
                ("name", lambda e: {"name": _front(e.name)}),
            ]
        for step, make in steps:
            wanted = {i: make(entries[i]) for i in pending}
            wanted = {i: ident for i, ident in wanted.items() if ident}
            unique = list({_ident_key(ident): ident for ident in wanted.values()}.values())
            if not unique:
                continue
            cards, _ = self.collection(unique)
            index = _CardIndex(cards)
            still = []
            for i in pending:
                ident = wanted.get(i)
                card = index.find(ident) if ident else None
                if card is None:
                    still.append(i)
                else:
                    method = step if step != "primary" else _ident_method(ident)
                    results[i] = Resolution(entries[i], card, method)
            pending = still
        for i in pending:
            results[i] = Resolution(entries[i], None, None)
        return results  # type: ignore[return-value]


class Resolution(NamedTuple):
    entry: CollectionEntry
    card: Card | None
    method: str | None  # "id" | "set_number" | "name_set" | "name" | None


def _front(name: str) -> str:
    return name.split(" // ")[0].strip()


def _ident_key(ident: dict[str, str]) -> tuple:
    return tuple(sorted((k, v.lower()) for k, v in ident.items()))


def _ident_method(ident: dict[str, str]) -> str:
    if "id" in ident:
        return "id"
    if "collector_number" in ident:
        return "set_number"
    return "name_set" if "set" in ident else "name"


class _CardIndex:
    """Finds the card in a /cards/collection response matching an identifier."""

    def __init__(self, cards: list[Card]):
        self.by_id = {c.id: c for c in cards}
        self.by_set_num = {(c.set_code, c.collector_number.lower()): c for c in cards}
        self.by_name_set: dict[tuple[str, str], Card] = {}
        self.by_name: dict[str, Card] = {}
        for c in cards:
            names = {c.name.lower(), _front(c.name).lower()}
            names |= {f.get("name", "").lower() for f in c.raw.get("card_faces", [])}
            for n in names - {""}:
                self.by_name_set.setdefault((n, c.set_code), c)
                self.by_name.setdefault(n, c)

    def find(self, ident: dict[str, str]) -> Card | None:
        if "id" in ident:
            return self.by_id.get(ident["id"])
        if "collector_number" in ident:
            return self.by_set_num.get((ident["set"].lower(), ident["collector_number"].lower()))
        name = ident["name"].lower()
        if "set" in ident:
            return self.by_name_set.get((name, ident["set"].lower()))
        return self.by_name.get(name)


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
