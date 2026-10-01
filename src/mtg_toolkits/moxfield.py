"""Moxfield collection CSV: read an export, write a file Moxfield imports.

Moxfield has no public API. Its web app's endpoints (``api2.moxfield.com``) are
undocumented and sit behind Cloudflare, and Moxfield grants programmatic access only on request
(support@moxfield.com, for some non-commercial uses). There is no OAuth for third parties,
so a user's private collection can't be fetched on their behalf. Files are the supported way
in and out: *Collection → More → Export CSV / Import CSV*. For decks, Moxfield's text export
(``1 Sol Ring (C21) 263``) is read by :func:`mtg_toolkits.decklist.parse_text`.

The collection CSV columns are ``Count, Tradelist Count, Name, Edition, Condition, Language,
Foil, Tags, Last Modified, Collector Number, Alter, Proxy, Purchase Price``. Reading
is lenient because files in the wild vary:
- conditions as ``NM`` or ``Near Mint``
- finishes as ``foil``, ``Foil``, ``etched`` or ``Normal``
- languages as names or codes
- extra or missing columns, and rows with more fields than the header (the overflow is ignored)
- prices in either locale (``1,234.50``, ``1.234,50``, ``€1.50``)

Conditions map onto the library's (Dragon Shield) scale the same way as the Archidekt export:
M, NM, LP (excellent), MP (light played), HP (played) and D (poor).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .dragonshield import LANGUAGE_NAMES, LANGUAGES
from .models import CollectionEntry, Condition, Finish
from .normalize import csv_errors_as_value_errors, normalize_set_code, parse_number, parse_quantity

COLUMNS = ["Count", "Tradelist Count", "Name", "Edition", "Condition", "Language", "Foil", "Tags",
           "Last Modified", "Collector Number", "Alter", "Proxy", "Purchase Price"]

CONDITIONS = {
    "m": Condition.MINT, "mint": Condition.MINT,
    "nm": Condition.NEAR_MINT, "near mint": Condition.NEAR_MINT, "near_mint": Condition.NEAR_MINT,
    "lp": Condition.EXCELLENT, "lightly played": Condition.EXCELLENT, "light played": Condition.EXCELLENT,
    "mp": Condition.LIGHT_PLAYED, "moderately played": Condition.LIGHT_PLAYED,
    "hp": Condition.PLAYED, "heavily played": Condition.PLAYED,
    "d": Condition.POOR, "damaged": Condition.POOR, "dmg": Condition.POOR,
}
CONDITION_NAMES = {
    Condition.MINT: "Mint", Condition.NEAR_MINT: "Near Mint", Condition.EXCELLENT: "Lightly Played",
    Condition.GOOD: "Lightly Played", Condition.LIGHT_PLAYED: "Moderately Played",
    Condition.PLAYED: "Heavily Played", Condition.POOR: "Damaged",
}
FINISHES = {"": Finish.NONFOIL, "normal": Finish.NONFOIL, "nonfoil": Finish.NONFOIL, "non-foil": Finish.NONFOIL,
            "foil": Finish.FOIL, "etched": Finish.ETCHED, "foil etched": Finish.ETCHED}
FINISH_NAMES = {Finish.NONFOIL: "", Finish.FOIL: "foil", Finish.ETCHED: "etched"}


def _num(value: str | None, cast=int, default=None):
    """A count (ValueError if malformed) or a price (``default`` if unreadable)."""
    if cast is int:
        return parse_quantity(value, default)
    number = parse_number(value)
    return default if number is None else cast(number)


def _date(value: str | None) -> date | None:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:26], fmt).date()
        except ValueError:
            continue
    return None


@csv_errors_as_value_errors
def parse(text: str) -> list[CollectionEntry]:
    """Parse a Moxfield collection CSV (as text) into entries."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not {"Count", "Name"} <= {f.strip() for f in reader.fieldnames}:
        raise ValueError("Not a Moxfield collection CSV: expected at least 'Count' and 'Name' columns")
    entries = []
    for raw in reader:
        # Fields beyond the header land under the key None (as a list): ignore them.
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k is not None}
        if not row.get("Name"):
            continue
        language = row.get("Language", "").lower()
        extra = {k: row[k] for k in ("Tags", "Alter", "Proxy", "Last Modified") if row.get(k)}
        raw_set = row.get("Edition", "")
        set_code = normalize_set_code(raw_set)
        if set_code and raw_set.lower() != set_code:  # an alias (e.g. GK2_ORZHOV): written back as read
            extra["Edition"] = raw_set
        entries.append(CollectionEntry(
            name=row["Name"],
            quantity=_num(row.get("Count"), int, 1),
            trade_quantity=_num(row.get("Tradelist Count"), int, 0),
            set_code=set_code,
            collector_number=row.get("Collector Number") or None,
            finish=FINISHES.get(row.get("Foil", "").lower(), Finish.NONFOIL),
            condition=CONDITIONS.get(row.get("Condition", "").lower(), Condition.NEAR_MINT),
            language=LANGUAGES.get(language, language if language in LANGUAGE_NAMES else "en"),
            purchase_price=_num(row.get("Purchase Price"), float),
            purchase_date=_date(row.get("Last Modified")),
            folder=row.get("Tags") or None,
            extra=extra,
        ))
    return entries


def read(path: str | Path) -> list[CollectionEntry]:
    return parse(Path(path).read_text(encoding="utf-8-sig"))


def dumps(entries: Iterable[CollectionEntry]) -> str:
    """Moxfield's import format. Folders become tags."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for e in entries:
        tags = e.extra.get("Tags") or e.folder or ""
        writer.writerow([
            e.quantity, e.trade_quantity or 0, e.name, e.extra.get("Edition") or (e.set_code or "").lower(), CONDITION_NAMES[e.condition],
            LANGUAGE_NAMES.get(e.language, e.language), FINISH_NAMES[e.finish], tags,
            e.extra.get("Last Modified") or (e.purchase_date.isoformat() if e.purchase_date else ""),
            e.collector_number or "", e.extra.get("Alter", "False"), e.extra.get("Proxy", "False"),
            "" if e.purchase_price is None else f"{e.purchase_price:.2f}",
        ])
    return out.getvalue()


def write(entries: Iterable[CollectionEntry], path: str | Path) -> int:
    entries = list(entries)
    Path(path).write_text(dumps(entries), encoding="utf-8")
    return len(entries)
