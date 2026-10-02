"""Service-neutral collection model shared by the importers/exporters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .normalize import _clean_number, normalize_set_code


class Finish(str, Enum):
    NONFOIL = "nonfoil"
    FOIL = "foil"
    ETCHED = "etched"


class Condition(str, Enum):
    """Card condition, ordered best to worst (Dragon Shield's scale)."""

    MINT = "mint"
    NEAR_MINT = "near_mint"
    EXCELLENT = "excellent"
    GOOD = "good"
    LIGHT_PLAYED = "light_played"
    PLAYED = "played"
    POOR = "poor"


@dataclass
class CollectionEntry:
    """One line of a collection: N copies of a specific printing in a specific state."""

    name: str
    quantity: int = 1
    set_code: str | None = None
    set_name: str | None = None
    collector_number: str | None = None
    finish: Finish = Finish.NONFOIL
    condition: Condition = Condition.NEAR_MINT
    language: str = "en"  # Scryfall language code
    folder: str | None = None
    trade_quantity: int = 0
    purchase_price: float | None = None
    purchase_date: date | None = None
    scryfall_id: str | None = None
    # Prices carried by the source file (e.g. Dragon Shield LOW/MID/MARKET), keyed by label.
    source_prices: dict[str, float] = field(default_factory=dict)
    extra: dict[str, str] = field(default_factory=dict)

    def scryfall_identifier(self) -> dict[str, str]:
        """Best identifier for Scryfall's ``/cards/collection`` endpoint.

        Set codes are normalised (:func:`~mtg_toolkits.normalize.normalize_set_code`, so
        Dragon Shield's ``GK2_ORZHOV`` is sent as ``gk2``), as are collector numbers
        (``"007"`` -> ``"7"``, ``"1*"`` -> ``"1★"``).
        """
        if self.scryfall_id:
            return {"id": self.scryfall_id}
        set_code, number = normalize_set_code(self.set_code), _clean_number(self.collector_number)
        if set_code and number:
            return {"set": set_code, "collector_number": number}
        if set_code:
            return {"name": self.name, "set": set_code}
        return {"name": self.name}
