"""Service-neutral collection model shared by the importers/exporters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


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
        """Best identifier for Scryfall's ``/cards/collection`` endpoint."""
        if self.scryfall_id:
            return {"id": self.scryfall_id}
        if self.set_code and self.collector_number:
            return {"set": self.set_code.lower(), "collector_number": self.collector_number}
        if self.set_code:
            return {"name": self.name, "set": self.set_code.lower()}
        return {"name": self.name}
