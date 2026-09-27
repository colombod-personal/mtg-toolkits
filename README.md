# mtg-toolkits

Tools and libraries for Magic: The Gathering projects: card data, pricing, decks and collections.

| Module | What it does |
|---|---|
| `mtg_toolkits.scryfall` | Scryfall client: card lookup, search, batched `/cards/collection`, bulk data, prices |
| `mtg_toolkits.archidekt` | Archidekt client (unofficial API): public decks, deck search, collection CSV export |
| `mtg_toolkits.dragonshield` | Dragon Shield Card Manager CSV reader and writer |
| `mtg_toolkits.enrich` | Joins a collection with Scryfall text, attributes and prices, and writes a report |

See [`docs/research.md`](docs/research.md) for API notes, limits, file formats and the pricing strategy.

## Install

```bash
pip install -e ".[dev]"
```

## CLI

```bash
mtgtk card "Sol Ring"                     # oracle text, attributes, prices
mtgtk card "delver" --fuzzy --json        # raw Scryfall JSON
mtgtk search "t:dragon c:r cmc<=4" --limit 20
mtgtk deck 123456                         # public Archidekt deck as a text list
mtgtk dragonshield price export.csv -o report.csv            # value your collection
mtgtk dragonshield to-archidekt export.csv archidekt.csv     # move collection to Archidekt
```

## Library

```python
from mtg_toolkits import dragonshield
from mtg_toolkits.scryfall import ScryfallClient
from mtg_toolkits.enrich import enrich, summarize

entries = dragonshield.read("export.csv")
with ScryfallClient() as sf:
    enriched = enrich(entries, sf)          # 75 cards per request, rate-limited
print(summarize(enriched))                  # {'cards': ..., 'total_usd': ..., ...}
```

## Tests

```bash
pytest
```

Tests use `httpx.MockTransport` and never touch the network.
