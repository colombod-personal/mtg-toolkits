"""Shared value normalisation for the readers, the matchers and callers.

Numbers (:func:`parse_number`) are read leniently, because collection files
come from apps in many locales:

* currency symbols (``$``, ``€``, ``£``) and spaces are ignored: ``"€ 1 234,50"``
* when both ``.`` and ``,`` appear, the last one is the decimal separator and
  the other separates thousands: ``"1,234.50"`` and ``"1.234,50"`` are 1234.5
* a lone ``,`` is a decimal comma when 1 or 2 digits follow it (``"1,50"`` is 1.5)
  and a thousands separator when exactly 3 do (``"1,234"`` is 1234). This is
  ambiguous by nature: no app writes prices with 3 decimals, so 3 digits mean thousands
* a lone ``.`` is always a decimal point (``"1.234"`` is 1.234); repeated
  ones (``"1.234.567"``) separate thousands
* anything else (exponents, ``inf``, ``nan``, letters) is not a number
"""

from __future__ import annotations

import csv
import functools
import math
import re

MAX_QUANTITY = 1_000_000  # copies on one line; anything above is a broken file

_CURRENCY = str.maketrans("", "", "$€£  ")
_PLAIN = re.compile(r"-?(?:\d+\.?\d*|\.\d+)")


def _plain(text: str, thousands: str, decimal: str) -> str:
    return text.replace(thousands, "").replace(decimal, ".")


def parse_number(value: str | None) -> float | None:
    """A price or quantity written in any common locale; None if blank or not a finite number."""
    text = (value or "").translate(_CURRENCY)
    if "." in text and "," in text:
        text = _plain(text, ",", ".") if text.rfind(".") > text.rfind(",") else _plain(text, ".", ",")
    elif "," in text:
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+", text):
            text = text.replace(",", "")
        elif text.count(",") == 1 and re.search(r",\d{1,2}$", text):
            text = text.replace(",", ".")
    elif text.count(".") > 1 and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    if not _PLAIN.fullmatch(text):
        return None
    number = float(text)
    return number if math.isfinite(number) else None


def parse_quantity(value: str | None, default: int = 1) -> int:
    """A whole number of copies in ``0..MAX_QUANTITY`` (``"2.0"`` is 2); ``default`` if blank.

    Raises ValueError for anything else, rather than guessing a count.
    """
    if not (value or "").strip():
        return default
    number = parse_number(value)
    if number is None or not number.is_integer() or not 0 <= number <= MAX_QUANTITY:
        raise ValueError(f"Invalid quantity: {value[:40]!r} (expected a whole number 0..{MAX_QUANTITY})")
    return int(number)


def csv_errors_as_value_errors(parse):
    """Decorate a reader so malformed CSV (e.g. an oversized field) raises ValueError, like other bad input."""

    @functools.wraps(parse)
    def wrapper(*args, **kwargs):
        try:
            return parse(*args, **kwargs)
        except csv.Error as exc:
            raise ValueError(f"Malformed CSV: {exc}") from None

    return wrapper
