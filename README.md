# mtg-toolkits

A Python library for Magic: The Gathering projects: card data, pricing, decks and collections.

| Module | What it does |
|---|---|
| `mtg_toolkits.scryfall` | Scryfall client: card lookup, search, batched `/cards/collection`, bulk data, prices |
| `mtg_toolkits.archidekt` | Archidekt client (unofficial API): public decks, deck search, collection CSV export |
| `mtg_toolkits.dragonshield` | Dragon Shield Card Manager CSV reader and writer |
| `mtg_toolkits.formats` | Detect, read and write collection files (Dragon Shield, Moxfield, Archidekt, generic CSV, text list) so collections can move between apps |
| `mtg_toolkits.moxfield` | Moxfield collection CSV reader and writer. Moxfield has no public API; see `docs/research.md` |
| `mtg_toolkits.delta` | Diffs collection snapshots (added/removed/changed), writes only the changes, deck coverage (owned/partial/missing) |
| `mtg_toolkits.decklist` | Parses pasted decklists (Archidekt, Moxfield, Arena, MTGO formats, sections, foil/etched) and deck URLs |
| `mtg_toolkits.enrich` | Joins a collection with Scryfall text, attributes and prices, and writes a report |
| `mtg_toolkits.normalize` | Set code / collector number normalisation (Dragon Shield aliases) and locale-tolerant number parsing |

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

Check a pasted decklist against your collection:

```python
from mtg_toolkits import decklist, delta

deck = decklist.parse_text(open("deck.txt").read())      # or ArchidektClient().get_deck(id).to_entries()
for line in delta.coverage(deck.to_entries(), owned=new):
    print(line.status, line.have, "/", line.need, line.entry.name)   # owned / partial / missing
```

Normalise set codes, collector numbers and prices the way the library matches them:

```python
from mtg_toolkits import normalize_set_code, normalize_collector_number, parse_number, set_alias_map

normalize_set_code(" GK2_ORZHOV ")      # 'gk2'  (strip, lower-case, Dragon Shield aliases)
normalize_collector_number("007*")      # '7★'   (lower-case, '*' -> '★', no leading zeros)
parse_number("1.234,50 €")              # 1234.5 (either decimal separator; "1,234" -> 1234)
set_alias_map()                         # {'legi': 'leg', 'gk2_orzhov': 'gk2', ...} to ship to a front end;
                                        # also map any code starting with normalize.SET_ALIAS_PREFIXES
                                        # ('gk1_', 'gk2_') to its first three characters
```

Match a collection against a Scryfall bulk file without loading every card:

```python
from mtg_toolkits.scryfall import Card, card_matches_keys, index_keys, iter_bulk_file, resolve_offline

keys = index_keys(entries)               # ids, (set, number) pairs and names, normalised like the matcher
cards = (Card.from_json(o) for o in iter_bulk_file("all-cards.jsonl.gz") if card_matches_keys(o, keys))
results = resolve_offline(entries, cards)  # prefers the entry's language, then English
```

## Tests

```bash
pytest
```

Tests use `httpx.MockTransport` and never touch the network.

## Data sources & thanks

This library is a thin layer over other people's generous work. If you build on it, please
credit them in your app too.

- **[Scryfall](https://scryfall.com)**: card data, images, bulk files and daily prices, which Scryfall sources
  from TCGplayer, Cardmarket and Cardhoarder. Follow [Scryfall's API terms](https://scryfall.com/docs/api):
  - send a descriptive User-Agent and respect the rate limits
  - don't paywall the data or imply that Scryfall endorses you
  - never crop card images or hide the artist credit

  [Support Scryfall](https://scryfall.com/donate).
- **[Archidekt](https://archidekt.com)**: public deck data through its open read API. Archidekt asks that you
  link back to it when you publish its data, and that you go easy on the API.
  [Support Archidekt](https://patreon.com/archidekt).
- **[Dragon Shield](https://mtg.dragonshield.com)** Card Manager: the CSV format this library reads and writes.
  Dragon Shield is a trademark of Arcane Tinmen ApS; this project isn't affiliated with them.
- Research help from [MtgCsvHelper](https://github.com/StepKie/MtgCsvHelper) and
  [pyrchidekt](https://github.com/linkian209/pyrchidekt).

mtg-toolkits is unofficial Fan Content permitted under the
[Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not approved/endorsed by Wizards.
Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.

## Licence

MIT (see [LICENSE](LICENSE)). The only runtime dependency is HTTPX, which is BSD-3-Clause. It
pulls in anyio (MIT), httpcore (BSD-3-Clause), h11 (MIT), idna (BSD-3-Clause) and certifi
(MPL-2.0, unmodified). There is no copyleft code. Magic: The Gathering names and card text
belong to Wizards of the Coast. Scryfall, Archidekt, Dragon Shield and Moxfield data and
formats are used for interoperability, under their own terms (see `docs/research.md`).
