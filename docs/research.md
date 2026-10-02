# Data source research

Notes from surveying the services this toolkit talks to (September 2026).
"Verified" means checked against the live docs or live API responses (fetched
through a web-extraction service, because this sandbox can't reach these
hosts directly). "Unverified" means reported by third parties only.

## Summary

| Source | Access | Card text / attributes | Prices | Collection / decks | Notes |
|---|---|---|---|---|---|
| **Scryfall** | Public REST API, no key | ✅ Complete (oracle text, faces, legalities, images, IDs) | ✅ Daily USD/EUR/TIX (TCGplayer, Cardmarket, Cardhoarder) | ❌ | Primary source. Bulk files for large jobs. |
| **Archidekt** | Unofficial JSON API, no key for public data | Partial (embedded in deck cards) | Partial (per-vendor prices on deck cards) | ✅ Public decks; collections via CSV only | Undocumented and may change. |
| **Moxfield** | No public API. Undocumented endpoints (`api2.moxfield.com`) behind Cloudflare; access is granted only on request (support@moxfield.com, some non-commercial uses). No OAuth for third parties | – | – | ✅ via collection CSV and deck text export | Use files. Ask Moxfield before calling its API. |
| **Dragon Shield Card Manager** | No API; CSV export/import from the app/web | Name, set, number only | LOW/MID/MARKET in export | ✅ via CSV (folders) | Offline file format. |
| **MTGJSON** | Free JSON/SQLite/CSV downloads | ✅ | ✅ `AllPrices` / `AllPricesToday` (TCGplayer, Cardmarket, Card Kingdom, Cardhoarder; buylist and retail) | ❌ | Best for price *history* (about 90 days) and vendor spread. |
| **TCGplayer API** | Closed to new developers | – | ✅ | – | Not a realistic option. Use Scryfall/MTGJSON instead. |
| **Cardmarket API** | Needs approved app plus OAuth, limited to sellers | – | ✅ EUR | – | Use Scryfall `eur` or MTGJSON instead. |
| **Card Kingdom** | Public price-list JSON (`/api/pricelist`) | – | ✅ retail and buylist | – | Unverified. Cheap to add later. |

## Scryfall — https://scryfall.com/docs/api

* **Headers are mandatory.** A descriptive `User-Agent` and an `Accept` header are required, and generic or missing values get blocked. Our `BaseClient` sets both.
* **Rate limits (verified, [docs](https://scryfall.com/docs/api/rate-limits)):** `/cards/search`, `/cards/named`, `/cards/random` and `/cards/collection` allow 2/s (500 ms), `/cards/manifest` allows 10/min, and everything else allows 10/s (100 ms). `*.scryfall.io` file downloads have no limit. A **429 locks you out for 30 s**, ignoring 429s is "not acceptable", and repeated overload can get the app banned. The client uses exactly these intervals and waits 30 s after a 429 (or honours `Retry-After`).
* **Key endpoints (implemented):**
  * `GET /cards/named?exact=|fuzzy=&set=` looks up a card by name.
  * `GET /cards/search?q=&unique=&order=` does a paginated full-text search. A search with no results returns **404**, which we treat as empty.
  * `POST /cards/collection` resolves up to **75** identifiers per call (`id`, `name`, `name+set`, `set+collector_number`, `multiverse_id`, `oracle_id`, `illustration_id`, `mtgo_id`). Responses include `not_found`.
  * `GET /cards/{id}` and `GET /cards/{set}/{number}[/{lang}]`
  * `GET /bulk-data` lists the bulk files: `oracle_cards` (about 23 MB), `unique_artwork`, `default_cards` (about 75 MB), `all_cards` (about 375 MB), `rulings`, `art_tags`, `oracle_tags`. **They are now gzipped JSON Lines** (`.jsonl.gz`), and the URL is in `jsonl_download_uri` (verified). Scryfall says to use them "if you need to rapidly look up card names, prices, or resolve a large number of card images". `download_bulk()` and `iter_bulk_file()` handle them.
  * `GET /cards/manifest` reports what changed, which is useful for incremental cache refresh (not implemented yet).
* **Prices.** `prices.{usd,usd_foil,usd_etched,eur,eur_foil,eur_etched,tix}` are strings or `null`, updated about once a day. Scryfall warns they are "dangerously stale" after 24 hours, so don't treat them as live market data, and cache per day. The link to the vendor listings is in `purchase_uris`.
* **Double-faced cards.** Top-level `mana_cost`, `oracle_text` and `image_uris` are absent. They live in `card_faces[]`, and `Card.from_json` merges them.
* **Terms.** Scryfall data is free to use. Don't paywall it, and don't re-host the images as your own. See https://scryfall.com/docs/api#use-of-scryfall-data-and-images.

## Archidekt — no official docs

* **Policy (verified, [forum reply from dev "michael"](https://archidekt.com/forum/thread/40353)):** they won't publish or maintain docs, but "our API is open and public (as far as reading is concerned)". Reverse-engineering from the browser network tab is fine. If you post their data publicly, **link back to Archidekt**. If third-party traffic becomes a problem they will lock the API down, so be gentle.
* `GET https://archidekt.com/api/decks/{id}/` returns the full deck (about 330 KB for a 100-card deck). Card fields were verified against a live response. The fields we rely on:
  * deck: `id, name, deckFormat (int), owner{username}, description, categories[{name, includedInDeck, includedInPrice, isPremier}], cards[]`
  * card entry: `quantity, modifier ("Normal"/"Foil"/"Etched"), categories[], deletedAt, card{uid (= Scryfall id), collectorNumber, edition{editioncode, editionname}, oracleCard{name, manaCost, text, types, cmc, colorIdentity, ...}, prices{tcg, tcgfoil, ck, ckfoil, cm, cmfoil, scg, cardTrader, mtgo, ... plus *Minimum variants}}`. There are also vendor ids (`tcgProductId`, `ckNormalId`, `ckFoilId`, `scgSku`, `cardTraderSku`), which are handy for vendor price lookups.
  * `oracleCard` includes Archidekt extras: `edhrecRank`, `salt`, `gameChanger`, `tutor`, `extraTurns`, `massLandDenial` and combo ids (`atomicCombos`, `potentialCombos`).
  * `description` is Quill "delta" JSON (`{"ops": [...]}`), not plain text.
* `GET /api/decks/v3/?name=&ownerUsername=&commanderName=&cardName=&deckFormat=&orderBy=&page=` searches decks. It returns `{count, next, results[{id, name, size, updatedAt, createdAt, deckFormat, edhBracket, featured, ...}]}` (verified: `ownerUsername=Wildcard` returned `count: 21`). There are about 50–60 results per page. `pageSize` seems to be ignored, and unknown `orderBy` values are silently ignored.
* The older `/api/decks/cards/?owner=&ownerexact=true` route now answers "Client Unavailable", so don't use it.
* Format ids: 1 Standard, 2 Modern, 3 Commander, 4 Legacy, 5 Vintage, 6 Pauper, 7 Custom, 8 Frontier, 9 Future Std, 10 Penny, 11 1v1 Cmdr, 12 Duel Cmdr, 13 Brawl, 14 Oathbreaker, 15 Pioneer, 16 Historic, 17 Pauper Cmdr, 18 Alchemy, 19 Explorer, 20 Historic Brawl.
* **Private decks and collections** require an account. Login is reportedly `POST /api/rest-auth/login/`, returning a JWT for `Authorization: JWT <token>`. This is unverified and not implemented. The collection importer accepts CSV with arbitrary headers mapped in the UI. `write_collection_csv` produces `Quantity, Name, Finish, Condition, Date Added, Language, Purchase Price, Tags, Edition Name, Edition Code, Collector Number, Scryfall ID`.
* Archidekt's conditions are `NM/LP/MP/HP/D`, finishes `Normal/Foil/Etched`, and languages `EN, JP, KR, CS, CT, …`.
* There is no published rate limit, so the client defaults to 1 request/second.

## Dragon Shield Card Manager / MTG Scanner

* There is no public API, no developer docs, and no third-party "sign in with Dragon Shield" (OAuth) access. Data leaves the app as a CSV export (whole collection or per folder), and the card manager also imports CSV.
* Collections live server-side (cloud sync, friends can view collections). The web app is at `mtg.dragonshield.com` and the account/login site at `auth.dragonshield.com`, so an internal API exists behind the web app. Automating it would mean reusing a user's logged-in session token against undocumented endpoints. That's brittle, and possibly against their T&C (the licence is "limited … for the purpose of accessing them"). **Next step if wanted:** capture a HAR of the web app loading folders (with credentials stripped) to map those endpoints, and/or ask Dragon Shield about partner access.
* **Verified against a real export** (14,597 rows / 21,950 copies / 269 sets, September 2026):
  * The file is UTF-8 with CRLF line endings, and the first line is a *quoted* `"sep=,"`. Fields containing a comma or an **apostrophe** are quoted (`"Commander Legends: Battle for Baldur's Gate"`).
  * Header: `Folder Name, Quantity, Trade Quantity, Card Name, Set Code, Set Name, Card Number, Condition, Printing, Language, Price Bought, Date Bought, LOW, MID, MARKET`
  * Condition: `Mint, NearMint, Excellent, Good, LightPlayed` were seen (`Played, Poor` exist too).
  * Printing: `Normal`, `Foil`, plus named foil treatments (`Oilslick Foil`, `Step and Compleat Foil`, `Surge Foil`, `Ripple Foil`, `Silver Foil`). It is **blank** on some etched-only printings (e.g. CLB 5xx–7xx, CMM 600, MH3 5xx).
  * Language: full English names (`English`, `Italian`, `Japanese`, …).
  * Dates are `yyyy-MM-dd`, and prices have 2 decimals.
  * Double-faced cards use the **full `Front // Back` name**. Older third-party notes claiming front-face-only are wrong for current exports.
  * Set codes are **Scryfall's codes, upper-cased**, including promo sets (`PWOE`, `POTJ`, `P30A`, `PLG21`) and The List's `SET-NUM` collector numbers (`C15-56`). The exceptions found are `GK2_ORZHOV` (Scryfall `gk2`) and `LEGI` ("Legends Italian", Scryfall `leg`). They're handled by `normalize.normalize_set_code` (exact aliases from `set_alias_map()`, plus the rule that any `gk1_`/`gk2_`-prefixed code maps to its first three characters), and the original code is kept for round-trips.
  * The same printing often appears on many rows (one per purchase date/price). This file has 2,830 such printings, and `delta.aggregate()` sums them.
  * `dragonshield.read()` + `dragonshield.write()` reproduces this file **byte for byte**.
* Quirks:
  * Column layout reportedly varies between users and app versions, so headers are matched by name.
  * An Excel `sep=<c>` first line may declare any delimiter, including a tab.
  * Prices may use a decimal comma (`1,50`) or thousands separators (`1.234,50`, `1,234.50`); see `normalize.parse_number` for the rules. A lone comma followed by exactly three digits (`1,234`) is read as a thousands separator.
  * Condition or Language values the library doesn't know are read as NearMint / English and the original string is written back.
  * Unknown set codes or collector numbers fall back to a name+set lookup, then name only, in `ScryfallClient.resolve_entries`. The result's `method` says which step matched.
* `LOW/MID/MARKET` are Dragon Shield's own USD prices (TCGplayer-derived) at export time.
* Existing converters for reference: [MtgCsvHelper](https://github.com/StepKie/MtgCsvHelper) (column mappings for about 10 sites), [DragonShield-to-Moxfield](https://github.com/KarmaKamikaze/DragonShield-to-Moxfield).

## Moxfield: no public API

- **No official API.** Moxfield publishes no developer API, and says the deck endpoints its site
  uses "were never officially supported". It grants access for "certain non-commercial uses" by
  e-mail (support@moxfield.com), by allow-listing the client's User-Agent. Its public issue tracker
  (github.com/moxfield/moxfield-public, issue 143) reports that even allow-listed clients hit
  Cloudflare challenges on the token endpoints.
- **No delegated login.** There is no OAuth or "connect your Moxfield account" flow. Signing in
  as the user would mean handling their Moxfield password, which isn't acceptable, and the private
  token endpoints are behind bot protection anyway. A user's private collection therefore can't be
  fetched on their behalf.
- **What works:**
  - **Collection CSV.** Moxfield → Collection → More → Export CSV (and Import CSV). The columns are
    `Count, Tradelist Count, Name, Edition, Condition, Language, Foil, Tags, Last Modified,
    Collector Number, Alter, Proxy, Purchase Price`. See `mtg_toolkits.moxfield`, which also
    converts a Dragon Shield collection into a file Moxfield imports.
  - **Deck text export.** Lines like `1 Sol Ring (C21) 263 *F*` are read by `decklist.parse_text`.
  - **Public deck URLs.** Only with Moxfield's permission (an allow-listed User-Agent). Since the
    Vault is free and non-commercial, it is a reasonable candidate to ask.

## Pricing strategy

1. **Default:** use Scryfall prices from `/cards/collection`, which is already done by `enrich()`. It's free, gives USD and EUR, and has foil/etched splits.
2. **History and vendor spread:** use MTGJSON `AllPricesToday.json` (daily) and `AllPrices.json` (about 90 days), keyed by MTGJSON UUID. Map to it through `AllIdentifiers` → `scryfallId`.
3. **Large collections:** download Scryfall's `default_cards` bulk file (`.jsonl.gz`) once a day and price locally with `iter_bulk_file()`. Don't make thousands of API calls.
4. **Vendor spread without extra APIs:** Archidekt deck cards already carry TCGplayer, Card Kingdom, Cardmarket, Star City Games and CardTrader prices, including foil and minimum variants.

## Ideas / next steps

- [ ] Local cache (SQLite) of Scryfall bulk data, with a daily price snapshot table for history.
- [ ] MTGJSON price client (`AllPricesToday`), keyed via `scryfallId`.
- [x] Set-code alias table for Dragon Shield → Scryfall mismatches (`SET_ALIASES`; extend as more turn up).
- [ ] Archidekt authenticated client (private decks, collection read/write) once verified against live responses.
- [ ] More formats: Moxfield, ManaBox, Deckbox CSV (see MtgCsvHelper mappings).
- [x] "What do I own from this deck?" by diffing an Archidekt deck against a Dragon Shield collection (`delta.shortfall`).
- [x] Snapshot deltas between exports (`delta.diff`).
- [x] MCP server exposing these tools to agents (in the Vault: `/api/mcp`).
- [ ] Moxfield public decks by URL, if Moxfield grants API access.

## Sources

- Scryfall API docs: https://scryfall.com/docs/api and rate limits: https://scryfall.com/docs/api/rate-limits
- Scryfall bulk data: https://scryfall.com/docs/api/bulk-data
- Archidekt forum threads on the API: https://archidekt.com/forum/thread/40353, https://archidekt.com/forum/thread/16962481, https://archidekt.com/forum/thread/10531812
- Dragon Shield terms: https://auth.dragonshield.com/TermsAndConditions/Index
- pyrchidekt (Archidekt JSON field names): https://github.com/linkian209/pyrchidekt
- MtgCsvHelper (Dragon Shield / Archidekt CSV mappings): https://github.com/StepKie/MtgCsvHelper
- Archidekt forum, Dragon Shield import format: https://archidekt.com/forum/thread/6162413/1
- Moxfield on its deck API ("never officially supported… we do offer access for certain non-commercial uses"): https://www.reddit.com/r/Moxfield/comments/1ubbry2/deck_api_no_longer_works
- Moxfield public issue tracker, allow-listed clients and Cloudflare: https://github.com/moxfield/moxfield-public/issues/143
- Moxfield collection CSV columns: https://software.codidact.com/posts/294785/294787
