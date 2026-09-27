# mtg-toolkits

A Python library for Magic: The Gathering projects: card data, pricing, decks and collections.

| Module | What it does |
|---|---|
| `mtg_toolkits.scryfall` | Scryfall client: card lookup, search, batched `/cards/collection`, bulk data, prices |
| `mtg_toolkits.archidekt` | Archidekt client (unofficial API): public decks, deck search, collection CSV export |
| `mtg_toolkits.dragonshield` | Dragon Shield Card Manager CSV reader and writer |
| `mtg_toolkits.delta` | Diffs collection snapshots (added/removed/changed), writes only the changes, finds what a deck is missing |
| `mtg_toolkits.enrich` | Joins a collection with Scryfall text, attributes and prices, and writes a report |

See [`docs/research.md`](docs/research.md) for API notes, limits, file formats and the pricing strategy.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```python
from mtg_toolkits.scryfall import ScryfallClient
from mtg_toolkits.archidekt import ArchidektClient

with ScryfallClient() as sf:
    card = sf.named("Sol Ring")
    print(card.oracle_text, card.prices.usd, card.prices.eur)
    dragons = list(sf.search("t:dragon c:r cmc<=4", limit=20))

with ArchidektClient() as ak:
    deck = ak.get_deck(123456)
    print(deck.to_text())
```

Price a Dragon Shield collection:

```python
from mtg_toolkits import dragonshield
from mtg_toolkits.scryfall import ScryfallClient
from mtg_toolkits.enrich import enrich, summarize

entries = dragonshield.read("export.csv")
with ScryfallClient() as sf:
    enriched = enrich(entries, sf)          # 75 cards per request, rate-limited
print(summarize(enriched))                  # {'cards': ..., 'total_usd': ..., ...}
```

Track changes between two exports, and find what a deck still needs:

```python
from mtg_toolkits import delta, dragonshield

old = dragonshield.read("export-2026-08.csv")
new = dragonshield.read("export-2026-09.csv")

d = delta.diff(old, new)                 # match on name + set + number + finish
print(d.summary())                       # {'added': 12, 'removed': 3, 'copies_in': 40, ...}
dragonshield.write(d.gains(), "new-cards.csv")     # import only what's new elsewhere
delta.write_csv(d, "changes.csv")        # human-readable change report

delta.diff(old, new, delta.BY_COPY, folders=True)  # stricter: condition, language, binder moves
missing = delta.shortfall(deck.to_entries(), owned=new)   # deck vs collection, by card name
```

## Tests

```bash
pytest
```

Tests use `httpx.MockTransport` and never touch the network.
