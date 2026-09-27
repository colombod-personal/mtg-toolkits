# Data source research

Notes from surveying the services this toolkit talks to (September 2026).
"Verified" means covered by code and tests in this repo. "Unverified" means
reported by third parties and not yet checked against live responses.

## Summary

| Source | Access | Card text / attributes | Prices | Collection / decks | Notes |
|---|---|---|---|---|---|
| **Scryfall** | Public REST API, no key | ✅ Complete (oracle text, faces, legalities, images, IDs) | ✅ Daily USD/EUR/TIX (TCGplayer, Cardmarket, Cardhoarder) | ❌ | Primary source. Bulk files for large jobs. |
| **Archidekt** | Unofficial JSON API, no key for public data | Partial (embedded in deck cards) | Partial (per-vendor prices on deck cards) | ✅ Public decks; collections via CSV only | Undocumented and may change. |
| **Dragon Shield Card Manager** | No API; CSV export/import from the app/web | Name, set, number only | LOW/MID/MARKET in export | ✅ via CSV (folders) | Offline file format. |
| **MTGJSON** | Free JSON/SQLite/CSV downloads | ✅ | ✅ `AllPrices` / `AllPricesToday` (TCGplayer, Cardmarket, Card Kingdom, Cardhoarder; buylist and retail) | ❌ | Best for price *history* (about 90 days) and vendor spread. |
| **TCGplayer API** | Closed to new developers | – | ✅ | – | Not a realistic option. Use Scryfall/MTGJSON instead. |
| **Cardmarket API** | Needs approved app plus OAuth, limited to sellers | – | ✅ EUR | – | Use Scryfall `eur` or MTGJSON instead. |
| **Card Kingdom** | Public price-list JSON (`/api/pricelist`) | – | ✅ retail and buylist | – | Unverified. Cheap to add later. |

## Scryfall — https://scryfall.com/docs/api

* **Headers are mandatory.** A descriptive `User-Agent` and an `Accept` header are required, and generic or missing values get blocked. Our `BaseClient` sets both.
* **Rate limit.** Keep sustained traffic under 10 req/s (50–100 ms between calls). `/cards/collection` has a hard cap of about 2 req/s, and search/named/random are also treated as expensive. The client spaces those "slow" endpoints 500 ms apart and everything else 100 ms apart. It retries on 429/5xx and honours `Retry-After`.
* **Key endpoints (implemented):**
  * `GET /cards/named?exact=|fuzzy=&set=` looks up a card by name.
  * `GET /cards/search?q=&unique=&order=` does a paginated full-text search. A search with no results returns **404**, which we treat as empty.
  * `POST /cards/collection` resolves up to **75** identifiers per call (`id`, `name`, `name+set`, `set+collector_number`, `multiverse_id`, `oracle_id`, `illustration_id`, `mtgo_id`). Responses include `not_found`.
  * `GET /cards/{id}` and `GET /cards/{set}/{number}[/{lang}]`
  * `GET /bulk-data` lists the bulk files: `oracle_cards`, `unique_artwork`, `default_cards`, `all_cards`, `rulings`. These are regenerated every 12 hours and are the right tool for whole-collection work or offline caches.
* **Prices.** `prices.{usd,usd_foil,usd_etched,eur,eur_foil,eur_etched,tix}` are strings or `null`, updated about once a day. Scryfall warns they are "dangerously stale" after 24 hours, so don't treat them as live market data, and cache per day. The link to the vendor listings is in `purchase_uris`.
* **Double-faced cards.** Top-level `mana_cost`, `oracle_text` and `image_uris` are absent. They live in `card_faces[]`, and `Card.from_json` merges them.
* **Terms.** Scryfall data is free to use. Don't paywall it, and don't re-host the images as your own. See https://scryfall.com/docs/api#use-of-scryfall-data-and-images.

## Archidekt — no official docs

* The maintainers (a two-person team) have said on the forum that they won't publish API docs, but the deck endpoint is fairly stable. Expect breakage.
* `GET https://archidekt.com/api/decks/{id}/` returns the full deck. The fields we rely on (confirmed against the `pyrchidekt` library's parser):
  * deck: `id, name, deckFormat (int), owner{username}, description, categories[{name, includedInDeck, includedInPrice, isPremier}], cards[]`
  * card entry: `quantity, modifier ("Normal"/"Foil"/"Etched"), categories[], deletedAt, card{uid (= Scryfall id), collectorNumber, edition{editioncode, editionname}, oracleCard{name, manaCost, text, types, cmc, colorIdentity, ...}, prices{tcg, ck, cm, ...}}`
* `GET /api/decks/v3/?name=&ownerUsername=&commanderName=&cardName=&deckFormat=&orderBy=&page=` searches decks. It returns `{count, next, results[]}` with about 50–60 results per page. `pageSize` seems to be ignored, and unknown `orderBy` values are silently ignored. `ownerUsername` is unverified.
* Format ids: 1 Standard, 2 Modern, 3 Commander, 4 Legacy, 5 Vintage, 6 Pauper, 7 Custom, 8 Frontier, 9 Future Std, 10 Penny, 11 1v1 Cmdr, 12 Duel Cmdr, 13 Brawl, 14 Oathbreaker, 15 Pioneer, 16 Historic, 17 Pauper Cmdr, 18 Alchemy, 19 Explorer, 20 Historic Brawl.
* **Private decks and collections** require an account. Login is reportedly `POST /api/rest-auth/login/`, returning a JWT for `Authorization: JWT <token>`. This is unverified and not implemented. The collection importer accepts CSV with arbitrary headers mapped in the UI. `write_collection_csv` produces `Quantity, Name, Finish, Condition, Date Added, Language, Purchase Price, Tags, Edition Name, Edition Code, Collector Number, Scryfall ID`.
* Archidekt's conditions are `NM/LP/MP/HP/D`, finishes `Normal/Foil/Etched`, and languages `EN, JP, KR, CS, CT, …`.
* There is no published rate limit, so the client defaults to 1 request/second.

## Dragon Shield Card Manager / MTG Scanner

* There is no public API. Data leaves the app as a CSV export (whole collection or per folder), and the card manager also imports CSV.
* The observed layout starts with an Excel `sep=,` line:
  `Folder Name, Quantity, Trade Quantity, Card Name, Set Code, Set Name, Card Number, Condition, Printing, Language, Price Bought, Date Bought, LOW, MID, MARKET`
* Values:
  * Condition: `Mint, NearMint, Excellent, Good, LightPlayed, Played, Poor`
  * Printing: `Normal, Foil` (there is no etched value)
  * Language: full English names such as `Japanese` or `Simplified Chinese`
  * Dates: `yyyy-MM-dd` or `M/d/yyyy`
* Quirks:
  * The column layout reportedly varies between users and app versions, so we match headers by name.
  * Double-faced cards export with the front-face name only.
  * Some set codes follow TCGplayer rather than Scryfall (promos, lists, token sets). These show up as "unmatched" in `mtgtk dragonshield price`. The fallback is name-only lookup, or a set-code alias table (TODO).
* `LOW/MID/MARKET` are Dragon Shield's own USD prices (TCGplayer-derived) at export time.
* Existing converters for reference: [MtgCsvHelper](https://github.com/StepKie/MtgCsvHelper) (column mappings for about 10 sites), [DragonShield-to-Moxfield](https://github.com/KarmaKamikaze/DragonShield-to-Moxfield).

## Pricing strategy

1. **Default:** use Scryfall prices from `/cards/collection`, which is already done by `enrich()`. It's free, gives USD and EUR, and has foil/etched splits.
2. **History and vendor spread:** use MTGJSON `AllPricesToday.json` (daily) and `AllPrices.json` (about 90 days), keyed by MTGJSON UUID. Map to it through `AllIdentifiers` → `scryfallId`.
3. **Large collections:** download Scryfall's `default_cards` bulk file once a day and price locally. Don't make thousands of API calls.

## Ideas / next steps

- [ ] Local cache (SQLite) of Scryfall bulk data, with a daily price snapshot table for history.
- [ ] MTGJSON price client (`AllPricesToday`), keyed via `scryfallId`.
- [ ] Set-code alias table for Dragon Shield → Scryfall mismatches.
- [ ] Archidekt authenticated client (private decks, collection read/write) once verified against live responses.
- [ ] More formats: Moxfield, ManaBox, Deckbox CSV (see MtgCsvHelper mappings).
- [ ] "What do I own from this deck?" by diffing an Archidekt deck against a Dragon Shield collection.
- [ ] Optional MCP server exposing these tools to Claude.

## Sources

- Scryfall API docs: https://scryfall.com/docs/api and rate limits: https://scryfall.com/docs/api/rate-limits
- Archidekt forum threads on the API: https://archidekt.com/forum/thread/40353, https://archidekt.com/forum/thread/16962481
- pyrchidekt (Archidekt JSON field names): https://github.com/linkian209/pyrchidekt
- MtgCsvHelper (Dragon Shield / Archidekt CSV mappings): https://github.com/StepKie/MtgCsvHelper
- Archidekt forum, Dragon Shield import format: https://archidekt.com/forum/thread/6162413/1
