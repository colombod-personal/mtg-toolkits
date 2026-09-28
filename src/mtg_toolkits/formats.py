"""Collection file formats in one place: detect, read and write, so collections can move
between apps.

    fmt, entries = formats.parse(text)            # Dragon Shield, Moxfield or generic CSV, detected
    text = formats.FORMATS["moxfield"].dumps(entries)

| name | reads | writes | for |
|---|---|---|---|
| ``dragonshield`` | ✅ | ✅ | Dragon Shield Card Manager (byte-identical round trip of its own exports) |
| ``moxfield`` | ✅ | ✅ | Moxfield collection import/export |
| ``archidekt`` | – | ✅ | Archidekt collection importer (map columns by header) |
| ``csv`` | ✅ | ✅ | Generic, lossless CSV: every field, including Scryfall ids, source prices and extras |
| ``text`` | – | ✅ | ``4 Lightning Bolt (M11) 149 *F*`` lines, which most deck sites and apps accept |
"""

from __future__ import annotations

import csv
import io
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable

from . import archidekt, dragonshield, moxfield
from .models import CollectionEntry, Condition, Finish

GENERIC_COLUMNS = ["quantity", "trade_quantity", "name", "set_code", "set_name", "collector_number", "finish",
                   "condition", "language", "folder", "purchase_price", "purchase_date", "scryfall_id",
                   "source_prices", "extra"]  # the last two are JSON objects (e.g. {"market": 1.5})


@dataclass(frozen=True)
class Format:
    name: str
    label: str
    extension: str
    media_type: str
    description: str
    dumps: Callable[[Iterable[CollectionEntry]], str]
    parse: Callable[[str], list[CollectionEntry]] | None = None


def dumps_generic(entries: Iterable[CollectionEntry]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(GENERIC_COLUMNS)
    for e in entries:
        writer.writerow([
            e.quantity, e.trade_quantity, e.name, e.set_code or "", e.set_name or "", e.collector_number or "",
            e.finish.value, e.condition.value, e.language, e.folder or "",
            "" if e.purchase_price is None else f"{e.purchase_price:.2f}",
            e.purchase_date.isoformat() if e.purchase_date else "", e.scryfall_id or "",
            json.dumps(e.source_prices, sort_keys=True) if e.source_prices else "",
            json.dumps(e.extra, sort_keys=True) if e.extra else "",
        ])
    return out.getvalue()


def parse_generic(text: str) -> list[CollectionEntry]:
    entries = []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        if not row.get("name"):
            continue
        entries.append(CollectionEntry(
            name=row["name"], quantity=int(row.get("quantity") or 1), trade_quantity=int(row.get("trade_quantity") or 0),
            set_code=row.get("set_code") or None, set_name=row.get("set_name") or None,
            collector_number=row.get("collector_number") or None,
            finish=Finish(row.get("finish") or "nonfoil"), condition=Condition(row.get("condition") or "near_mint"),
            language=row.get("language") or "en", folder=row.get("folder") or None,
            purchase_price=float(row["purchase_price"]) if row.get("purchase_price") else None,
            purchase_date=date.fromisoformat(row["purchase_date"]) if row.get("purchase_date") else None,
            scryfall_id=row.get("scryfall_id") or None,
            source_prices={k: float(v) for k, v in json.loads(row["source_prices"]).items()} if row.get("source_prices") else {},
            extra={k: str(v) for k, v in json.loads(row["extra"]).items()} if row.get("extra") else {},
        ))
    return entries


def dumps_text(entries: Iterable[CollectionEntry]) -> str:
    """One line per printing and finish (conditions and folders merged)."""
    counts: OrderedDict[tuple, int] = OrderedDict()
    for e in entries:
        key = (e.name, (e.set_code or "").upper(), e.collector_number or "", e.finish)
        counts[key] = counts.get(key, 0) + e.quantity
    lines = []
    for (name, set_code, number, finish), qty in counts.items():
        where = f" ({set_code}) {number}".rstrip() if set_code else ""
        mark = {Finish.FOIL: " *F*", Finish.ETCHED: " *E*"}.get(finish, "")
        lines.append(f"{qty} {name}{where}{mark}")
    return "\n".join(lines) + "\n"


FORMATS: dict[str, Format] = {f.name: f for f in [
    Format("dragonshield", "Dragon Shield", "csv", "text/csv",
           "Dragon Shield Card Manager CSV. Your own export comes back byte for byte.",
           dragonshield.dumps, dragonshield.parse),
    Format("moxfield", "Moxfield", "csv", "text/csv",
           "Moxfield collection CSV (Collection → More → Import CSV). Folders become tags.",
           moxfield.dumps, moxfield.parse),
    Format("archidekt", "Archidekt", "csv", "text/csv",
           "Archidekt collection importer CSV; map the columns by header. Includes Scryfall ids.",
           archidekt.dumps_collection_csv),
    Format("csv", "Generic CSV", "csv", "text/csv",
           "Every field, including Scryfall ids, in plain columns. Lossless: re-importable here.",
           dumps_generic, parse_generic),
    Format("text", "Text list", "txt", "text/plain",
           "'4 Lightning Bolt (M11) 149 *F*' lines, accepted by most deck sites and apps.",
           dumps_text),
]}


def detect(text: str) -> str | None:
    """Which readable format ``text`` is, from its header; None if unknown."""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines:
        return None
    first = lines[0].strip().strip('"').lower()
    declared = first[4:] if first.startswith("sep=") and len(first) == 5 else None  # Excel's "sep=X" line
    header = lines[1] if declared and len(lines) > 1 else lines[0]
    cols = {c.strip().strip('"').lower() for c in next(csv.reader([header], delimiter=declared or ","), [])}
    if {"card name", "quantity"} <= cols or declared:
        return "dragonshield"
    if {"count", "name"} <= cols:
        return "moxfield"
    if {"quantity", "name", "set_code", "finish", "condition"} <= cols:
        return "csv"
    return None


def parse(text: str, fmt: str | None = None) -> tuple[str, list[CollectionEntry]]:
    """Read a collection file. Raises ValueError naming the supported formats if unrecognised."""
    fmt = fmt or detect(text)
    readable = [f.label for f in FORMATS.values() if f.parse]
    if fmt is None or FORMATS.get(fmt) is None or FORMATS[fmt].parse is None:
        raise ValueError(f"Unrecognised collection file. Supported: {', '.join(readable)} CSV exports.")
    return fmt, FORMATS[fmt].parse(text)
