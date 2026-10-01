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
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable

from . import archidekt, dragonshield, moxfield
from .models import CollectionEntry, Condition, Finish
from .normalize import csv_errors_as_value_errors, parse_number, parse_quantity

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


def parse_finish(value: str | None) -> Finish:
    """``nonfoil``/``foil``/``etched`` in any case, or a common spelling (``Normal``, ``Foil Etched``)."""
    text = (value or "").strip().lower()
    finish = moxfield.FINISHES.get(text) or Finish._value2member_map_.get(text)
    if finish is None:
        raise ValueError(f"Unknown finish: {value!r}")
    return finish


def parse_condition(value: str | None) -> Condition:
    """A :class:`Condition` value in any case or spacing (``near_mint``, ``Near Mint``, ``LightPlayed``),
    or a grading abbreviation (``NM``, ``LP``, ``MP``, ``HP``, ``DMG``) mapped as Moxfield's are."""
    text = (value or "near_mint").strip().lower()
    by_value = {c.value.replace("_", ""): c for c in Condition}
    condition = by_value.get(re.sub(r"[\s_-]", "", text)) or moxfield.CONDITIONS.get(text)
    if condition is None:
        raise ValueError(f"Unknown condition: {value!r}")
    return condition


def _json_object(row: dict[str, str], column: str) -> dict:
    data = json.loads(row.get(column) or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"{column} must be a JSON object, got {row[column][:40]!r}")
    return data


def _source_prices(row: dict[str, str]) -> dict[str, float]:
    prices, out = _json_object(row, "source_prices"), {}
    for k, v in prices.items():
        try:  # a JSON integer can be too large for a float
            number = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else math.nan
        except OverflowError:
            number = math.nan
        if not math.isfinite(number):
            raise ValueError(f"source_prices values must be numbers: {row['source_prices'][:40]!r}")
        out[k] = number
    return out


@csv_errors_as_value_errors
def parse_generic(text: str) -> list[CollectionEntry]:
    """Read :func:`dumps_generic` output. Lenient about spellings (``Foil``, ``NM``, ``1,50``,
    ``2.0``); raises ValueError on values it can't read rather than guessing."""
    entries = []
    for raw in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k is not None}  # None: overflow fields
        if not row.get("name"):
            continue
        entries.append(CollectionEntry(
            name=row["name"], quantity=parse_quantity(row.get("quantity"), 1),
            trade_quantity=parse_quantity(row.get("trade_quantity"), 0),
            set_code=row.get("set_code") or None, set_name=row.get("set_name") or None,
            collector_number=row.get("collector_number") or None,
            finish=parse_finish(row.get("finish")), condition=parse_condition(row.get("condition")),
            language=row.get("language") or "en", folder=row.get("folder") or None,
            purchase_price=parse_number(row.get("purchase_price")),
            purchase_date=date.fromisoformat(row["purchase_date"]) if row.get("purchase_date") else None,
            scryfall_id=row.get("scryfall_id") or None,
            source_prices=_source_prices(row),
            extra={k: "" if v is None else str(v) for k, v in _json_object(row, "extra").items()},
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
    first = lines[0].strip('\r\n "').lower()  # not str.strip(): "sep=\t" declares a tab
    declared = first[4:] if first.startswith("sep=") and len(first) == 5 else None  # Excel's "sep=X" line
    header = lines[1] if declared and len(lines) > 1 else lines[0]
    try:
        cols = {c.strip().strip('"').lower() for c in next(csv.reader([header], delimiter=declared or ","), [])}
    except csv.Error:  # e.g. a field over the csv module's size limit: not a file we know
        return None
    if {"card name", "quantity"} <= cols or (declared and "card name" in cols):
        return "dragonshield"
    if {"count", "name"} <= cols:
        return "moxfield"
    if {"quantity", "name", "set_code", "finish", "condition"} <= cols:
        return "csv"
    return None


def parse(text: str, fmt: str | None = None) -> tuple[str, list[CollectionEntry]]:
    """Read a collection file. Raises ValueError (only) on bad input, naming the supported formats if unrecognised."""
    fmt = fmt or detect(text)
    readable = [f.label for f in FORMATS.values() if f.parse]
    if fmt is None or FORMATS.get(fmt) is None or FORMATS[fmt].parse is None:
        raise ValueError(f"Unrecognised collection file. Supported: {', '.join(readable)} CSV exports.")
    return fmt, FORMATS[fmt].parse(text)
