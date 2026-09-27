"""Dragon Shield Card Manager / MTG Scanner CSV import & export.

Dragon Shield has no public API; the app (and web card manager) export a CSV
per folder or for the whole collection. Layout of a real export (UTF-8, CRLF)::

    "sep=,"
    Folder Name,Quantity,Trade Quantity,Card Name,Set Code,Set Name,Card Number,Condition,Printing,Language,Price Bought,Date Bought,LOW,MID,MARKET

Quirks handled here:

* An optional Excel ``sep=<c>`` first line (quoted or not) declaring the delimiter.
* Columns are matched by header name, so re-ordered or missing columns work.
* Condition values: Mint, NearMint, Excellent, Good, LightPlayed, Played, Poor.
* Printing values: Normal, Foil, and named foil treatments ("Oilslick Foil",
  "Surge Foil", "Step and Compleat Foil", "Ripple Foil", "Silver Foil", ...),
  which map to :attr:`Finish.FOIL`. Printing is sometimes blank (seen on
  etched-only printings); that maps to NONFOIL, and
  :func:`mtg_toolkits.enrich.enrich` corrects it from Scryfall's ``finishes``.
  Any non-plain value is kept in ``entry.extra["Printing"]`` so writing the
  file back is lossless.
* Languages are English names ("Japanese"), mapped to Scryfall codes ("ja").
* Double-faced cards use the full ``"Front // Back"`` name.
* Set codes are mostly Scryfall's (including promo sets like ``PWOE`` and The
  List numbers like ``C15-56``). A few Dragon Shield-only codes are mapped via
  :data:`SET_ALIASES`; the original is kept in ``entry.extra["Set Code"]``.
* The same printing often appears on several rows (one per purchase), so use
  :func:`mtg_toolkits.delta.aggregate` to get totals.
* ``LOW``/``MID``/``MARKET`` are Dragon Shield's own (TCGplayer-derived) USD prices.
* Dates appear as ``yyyy-MM-dd`` or ``M/d/yyyy``.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .models import CollectionEntry, Condition, Finish

COLUMNS = [
    "Folder Name", "Quantity", "Trade Quantity", "Card Name", "Set Code", "Set Name",
    "Card Number", "Condition", "Printing", "Language", "Price Bought", "Date Bought",
    "LOW", "MID", "MARKET",
]
PRICE_COLUMNS = ("LOW", "MID", "MARKET")

CONDITIONS = {
    "mint": Condition.MINT,
    "nearmint": Condition.NEAR_MINT,
    "excellent": Condition.EXCELLENT,
    "good": Condition.GOOD,
    "lightplayed": Condition.LIGHT_PLAYED,
    "played": Condition.PLAYED,
    "poor": Condition.POOR,
}
CONDITION_NAMES = {
    Condition.MINT: "Mint", Condition.NEAR_MINT: "NearMint", Condition.EXCELLENT: "Excellent",
    Condition.GOOD: "Good", Condition.LIGHT_PLAYED: "LightPlayed", Condition.PLAYED: "Played",
    Condition.POOR: "Poor",
}
LANGUAGES = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de", "italian": "it",
    "portuguese": "pt", "japanese": "ja", "korean": "ko", "russian": "ru",
    "simplified chinese": "zhs", "chinese simplified": "zhs",
    "traditional chinese": "zht", "chinese traditional": "zht",
}
LANGUAGE_NAMES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "ja": "Japanese", "ko": "Korean", "ru": "Russian",
    "zhs": "Simplified Chinese", "zht": "Traditional Chinese",
}


# Dragon Shield set code (lower-case) -> Scryfall set code.
SET_ALIASES = {
    "gk1_boros": "gk1", "gk1_dimir": "gk1", "gk1_golgari": "gk1", "gk1_izzet": "gk1", "gk1_selesn": "gk1",
    "gk1_selesnya": "gk1",
    "gk2_azorius": "gk2", "gk2_gruul": "gk2", "gk2_orzhov": "gk2", "gk2_rakdos": "gk2", "gk2_simic": "gk2",
    "legi": "leg",  # "Legends Italian"
}
PLAIN_PRINTINGS = {"normal", "foil"}


def scryfall_set_code(code: str | None) -> str | None:
    """Translate a Dragon Shield set code to Scryfall's (unknown codes pass through)."""
    if not code:
        return None
    lowered = code.strip().lower()
    if lowered in SET_ALIASES:
        return SET_ALIASES[lowered]
    if lowered.startswith(("gk1_", "gk2_")):
        return lowered[:3]
    return code


def _finish(printing: str) -> Finish:
    p = printing.lower()
    if "etched" in p:
        return Finish.ETCHED
    return Finish.FOIL if "foil" in p else Finish.NONFOIL


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip().lstrip("$€£")
    # "1,50" (decimal comma) vs "1,234.50" (thousands separator)
    value = value.replace(",", ".") if ("," in value and "." not in value) else value.replace(",", "")
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _quantity(value: str | None) -> int:
    """Missing or blank means 1; an explicit 0 stays 0."""
    q = _float(value)
    return 1 if q is None else int(q)


def _date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19] if "T" in value else value, fmt).date()
        except ValueError:
            continue
    return None


_KNOWN = {_norm(c) for c in COLUMNS}


def parse(text: str) -> list[CollectionEntry]:
    """Parse the contents of a Dragon Shield CSV export."""
    text = text.lstrip("﻿")
    delimiter = ","
    first, _, rest = text.partition("\n")
    marker = first.strip().strip('"').strip()
    if marker.lower().startswith("sep="):
        delimiter = marker[4:5] or ","
        text = rest
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return []
    index = {_norm(h): i for i, h in enumerate(header)}

    def col(row: list[str], name: str) -> str | None:
        i = index.get(_norm(name))
        return row[i].strip() if i is not None and i < len(row) else None

    entries = []
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        name = col(row, "Card Name")
        if not name:
            continue
        printing = col(row, "Printing") or ""
        raw_set = col(row, "Set Code") or None
        set_code = scryfall_set_code(raw_set)
        extra = {h: row[i] for i, h in enumerate(header) if _norm(h) not in _KNOWN and i < len(row)}
        if printing.lower() not in PLAIN_PRINTINGS:
            extra["Printing"] = printing
        if raw_set and set_code != raw_set:
            extra["Set Code"] = raw_set
        prices = {p.lower(): v for p in PRICE_COLUMNS if (v := _float(col(row, p))) is not None}
        entries.append(
            CollectionEntry(
                name=name,
                quantity=_quantity(col(row, "Quantity")),
                trade_quantity=int(_float(col(row, "Trade Quantity")) or 0),
                set_code=set_code,
                set_name=(col(row, "Set Name") or None),
                collector_number=(col(row, "Card Number") or None),
                condition=CONDITIONS.get(_norm(col(row, "Condition") or ""), Condition.NEAR_MINT),
                finish=_finish(printing),
                language=LANGUAGES.get((col(row, "Language") or "english").lower(), "en"),
                folder=col(row, "Folder Name") or None,
                purchase_price=_float(col(row, "Price Bought")),
                purchase_date=_date(col(row, "Date Bought")),
                source_prices=prices,
                extra=extra,
            )
        )
    return entries


def read(path: str | Path) -> list[CollectionEntry]:
    return parse(Path(path).read_text(encoding="utf-8-sig"))


def _printing(e: CollectionEntry) -> str:
    original = e.extra.get("Printing")
    if original is not None and _finish(original) is e.finish or (original == "" and e.finish is Finish.ETCHED):
        return original
    return "Normal" if e.finish is Finish.NONFOIL else "Foil"


def _row(values: Iterable[object]) -> str:
    """One CRLF-terminated line, quoted the way the app does it: any field
    containing a comma, double quote, apostrophe or line break is quoted."""
    out = []
    for value in values:
        text = str(value)
        if any(ch in text for ch in ",\"'\r\n"):
            text = '"' + text.replace('"', '""') + '"'
        out.append(text)
    return ",".join(out) + "\r\n"


def dumps(entries: Iterable[CollectionEntry], *, sep_line: bool = True) -> str:
    """Serialise entries in the same layout the app exports (quoted sep line, CRLF).

    Reading an export and writing it back reproduces the file byte for byte.
    """
    buf = io.StringIO()
    if sep_line:
        buf.write('"sep=,"\r\n')
    buf.write(_row(COLUMNS))
    for e in entries:
        buf.write(_row([
            e.folder or "",
            e.quantity,
            e.trade_quantity,
            e.name,
            e.extra.get("Set Code") or (e.set_code or "").upper(),
            e.set_name or "",
            e.collector_number or "",
            CONDITION_NAMES[e.condition],
            _printing(e),
            LANGUAGE_NAMES.get(e.language, e.language),
            f"{e.purchase_price:.2f}" if e.purchase_price is not None else "",
            e.purchase_date.isoformat() if e.purchase_date else "",
            *[f"{e.source_prices[p.lower()]:.2f}" if p.lower() in e.source_prices else "" for p in PRICE_COLUMNS],
        ]))
    return buf.getvalue()


def write(entries: Iterable[CollectionEntry], path: str | Path, **kwargs) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as fh:  # keep CRLF as written
        fh.write(dumps(entries, **kwargs))
