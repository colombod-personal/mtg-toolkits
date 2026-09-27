"""``mtgtk`` command line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from . import dragonshield
from .archidekt import ArchidektClient, write_collection_csv
from .enrich import enrich, summarize, write_report
from .scryfall import ScryfallClient


def _card_cmd(args) -> int:
    with ScryfallClient() as sf:
        card = sf.named(args.name, fuzzy=args.fuzzy, set_code=args.set)
    if args.json:
        print(json.dumps(card.raw, indent=2))
        return 0
    print(f"{card.name}  {card.mana_cost or ''}")
    print(f"{card.type_line}  [{card.set_code.upper()} #{card.collector_number}, {card.rarity}]")
    if card.oracle_text:
        print(card.oracle_text)
    if card.power is not None:
        print(f"{card.power}/{card.toughness}")
    p = card.prices
    print(f"USD {p.usd}  foil {p.usd_foil}  |  EUR {p.eur}  foil {p.eur_foil}  |  TIX {p.tix}")
    print(card.scryfall_uri)
    return 0


def _search_cmd(args) -> int:
    with ScryfallClient() as sf:
        for card in sf.search(args.query, limit=args.limit):
            print(f"{card.name:40} {card.set_code.upper():6} {card.prices.usd or '-':>8}  {card.type_line}")
    return 0


def _deck_cmd(args) -> int:
    with ArchidektClient() as ak:
        deck = ak.get_deck(args.deck_id)
    if args.json:
        print(json.dumps(deck.raw, indent=2))
    else:
        print(f"// {deck.name} by {deck.owner}")
        print(deck.to_text(include_excluded=args.all))
    return 0


def _ds_convert_cmd(args) -> int:
    entries = dragonshield.read(args.input)
    n = write_collection_csv(entries, args.output, folder_as_tag=not args.no_tags)
    print(f"Wrote {n} rows to {args.output}", file=sys.stderr)
    return 0


def _ds_price_cmd(args) -> int:
    entries = dragonshield.read(args.input)
    with ScryfallClient() as sf:
        enriched = enrich(entries, sf)
    if args.output:
        write_report(enriched, args.output)
    for key, value in summarize(enriched).items():
        print(f"{key:>10}: {value}")
    for item in enriched:
        if item.card is None:
            e = item.entry
            print(f"  unmatched: {e.name} ({e.set_code} {e.collector_number})", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mtgtk", description="MTG data toolkit")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("card", help="Look up a card on Scryfall")
    c.add_argument("name")
    c.add_argument("--fuzzy", action="store_true")
    c.add_argument("--set")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=_card_cmd)

    s = sub.add_parser("search", help="Scryfall full-text search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=_search_cmd)

    d = sub.add_parser("deck", help="Fetch a public Archidekt deck")
    d.add_argument("deck_id")
    d.add_argument("--json", action="store_true")
    d.add_argument("--all", action="store_true", help="include maybeboard/sideboard")
    d.set_defaults(func=_deck_cmd)

    ds = sub.add_parser("dragonshield", help="Dragon Shield CSV tools").add_subparsers(dest="ds", required=True)
    conv = ds.add_parser("to-archidekt", help="Convert a Dragon Shield export to an Archidekt collection CSV")
    conv.add_argument("input")
    conv.add_argument("output")
    conv.add_argument("--no-tags", action="store_true", help="don't turn folder names into tags")
    conv.set_defaults(func=_ds_convert_cmd)
    price = ds.add_parser("price", help="Price a Dragon Shield export using Scryfall")
    price.add_argument("input")
    price.add_argument("-o", "--output", help="write a detailed CSV report")
    price.set_defaults(func=_ds_price_cmd)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
