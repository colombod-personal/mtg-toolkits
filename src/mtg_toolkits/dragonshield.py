"""Dragon Shield Card Manager / MTG Scanner CSV import & export.

Dragon Shield has no public API; the app (and web card manager) export a CSV
per folder or for the whole collection. Observed layout::

    sep=,
    Folder Name,Quantity,Trade Quantity,Card Name,Set Code,Set Name,Card Number,Condition,Printing,Language,Price Bought,Date Bought,LOW,MID,MARKET

Quirks handled here:

* An optional Excel ``sep=<c>`` first line that declares the delimiter.
* Columns are matched by header name, so re-ordered or missing columns work.
* Condition values: Mint, NearMint, Excellent, Good, LightPlayed, Played, Poor.
* Printing values: Normal, Foil (no etched finish).
* Languages are English names ("Japanese"), mapped to Scryfall codes ("ja").
* Double-faced cards use the front-face name only.
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
    if first.strip().lower().startswith("sep="):
        delimiter = first.strip()[4:5] or ","
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
        printing = (col(row, "Printing") or "").lower()
        prices = {p.lower(): v for p in PRICE_COLUMNS if (v := _float(col(row, p))) is not None}
        entries.append(
            CollectionEntry(
                name=name,
                quantity=int(_float(col(row, "Quantity")) or 1),
                trade_quantity=int(_float(col(row, "Trade Quantity")) or 0),
                set_code=(col(row, "Set Code") or None),
                set_name=(col(row, "Set Name") or None),
                collector_number=(col(row, "Card Number") or None),
                condition=CONDITIONS.get(_norm(col(row, "Condition") or ""), Condition.NEAR_MINT),
                finish=Finish.FOIL if "foil" in printing else (Finish.ETCHED if "etched" in printing else Finish.NONFOIL),
                language=LANGUAGES.get((col(row, "Language") or "english").lower(), "en"),
                folder=col(row, "Folder Name") or None,
                purchase_price=_float(col(row, "Price Bought")),
                purchase_date=_date(col(row, "Date Bought")),
                source_prices=prices,
                extra={h: row[i] for i, h in enumerate(header) if _norm(h) not in _KNOWN and i < len(row)},
            )
        )
    return entries


def read(path: str | Path) -> list[CollectionEntry]:
    return parse(Path(path).read_text(encoding="utf-8-sig"))


def dumps(entries: Iterable[CollectionEntry], *, sep_line: bool = True) -> str:
    """Serialise entries back to Dragon Shield's CSV layout."""
    buf = io.StringIO()
    if sep_line:
        buf.write("sep=,\n")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(COLUMNS)
    for e in entries:
        writer.writerow([
            e.folder or "",
            e.quantity,
            e.trade_quantity,
            e.name.split(" // ")[0],
            (e.set_code or "").upper(),
            e.set_name or "",
            e.collector_number or "",
            CONDITION_NAMES[e.condition],
            "Foil" if e.finish is not Finish.NONFOIL else "Normal",
            LANGUAGE_NAMES.get(e.language, e.language),
            f"{e.purchase_price:.2f}" if e.purchase_price is not None else "",
            e.purchase_date.isoformat() if e.purchase_date else "",
            *[f"{e.source_prices[p.lower()]:.2f}" if p.lower() in e.source_prices else "" for p in PRICE_COLUMNS],
        ])
    return buf.getvalue()


def write(entries: Iterable[CollectionEntry], path: str | Path, **kwargs) -> None:
    Path(path).write_text(dumps(entries, **kwargs), encoding="utf-8")
