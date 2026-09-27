"""Parse plain-text decklists and deck-site URLs.

Handles the formats people paste from Archidekt, Moxfield, MTG Arena, MTGO and
most other sites::

    4 Lightning Bolt
    4x Lightning Bolt
    1 Sol Ring (C21) 263
    1 Sol Ring [CMR]
    1x Sol Ring (c21) 263 *F* [Ramp]        # Archidekt export: finish + category
    SB: 2 Duress                            # MTGO sideboard prefix

Section headers switch where following lines go: ``Commander``, ``Deck`` /
``Mainboard``, ``Sideboard``, ``Maybeboard`` / ``Considering``, ``Companion``,
written bare, with a trailing colon, or as ``// Sideboard`` comments. A
bracketed Archidekt category that names a section (``[Sideboard]``,
``[Maybeboard]``, ``[Commander]``) wins over the header.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .models import CollectionEntry, Finish

MAIN = "main"
SECTIONS = {
    "commander": "commander", "commanders": "commander",
    "companion": "companion", "companions": "companion",
    "deck": MAIN, "main": MAIN, "mainboard": MAIN, "main deck": MAIN,
    "sideboard": "sideboard", "side": "sideboard",
    "maybeboard": "maybeboard", "maybe": "maybeboard", "considering": "maybeboard",
}
PLAYED_SECTIONS = (MAIN, "commander", "companion")

_HEADER = re.compile(r"^(?://|#)?\s*([A-Za-z ]+?)\s*:?\s*(?:\(\d+\))?$")
_LINE = re.compile(
    r"""^(?P<qty>\d+)\s*x?\s+
        (?P<name>.+?)
        # (SET) in parentheses, or [SET] in brackets only when it looks like a set code
        # (upper-case, 2-6 chars); anything else in brackets is an Archidekt category.
        (?:\s+(?:\((?P<set>[A-Za-z0-9_]{2,10})\)|\[(?P<bset>[A-Z0-9]{2,6})\])(?:\s+(?P<num>[A-Za-z0-9★†-]+))?)?
        (?:\s+\*(?P<finish>[FE])\*)?
        (?:\s+\[(?P<cats>[^\]]*)\])?
        (?:\s+\^[^^]*\^)?\s*$""",
    re.VERBOSE,
)


@dataclass
class DeckLine:
    quantity: int
    name: str
    set_code: str | None = None
    collector_number: str | None = None
    finish: Finish = Finish.NONFOIL
    section: str = MAIN
    categories: list[str] = field(default_factory=list)

    def to_entry(self) -> CollectionEntry:
        return CollectionEntry(
            name=self.name, quantity=self.quantity, set_code=self.set_code,
            collector_number=self.collector_number, finish=self.finish,
        )


@dataclass
class Decklist:
    lines: list[DeckLine]
    name: str | None = None
    unparsed: list[str] = field(default_factory=list)

    def section(self, *names: str) -> list[DeckLine]:
        return [line for line in self.lines if line.section in names]

    def to_entries(self, sections: tuple[str, ...] = PLAYED_SECTIONS) -> list[CollectionEntry]:
        """Collection entries for the chosen sections (default: what's actually played)."""
        return [line.to_entry() for line in self.lines if line.section in sections]

    @property
    def card_count(self) -> int:
        return sum(line.quantity for line in self.section(*PLAYED_SECTIONS))


def parse_text(text: str, name: str | None = None) -> Decklist:
    """Parse a pasted decklist. Lines that aren't cards or headers go to ``unparsed``."""
    lines: list[DeckLine] = []
    unparsed: list[str] = []
    section = MAIN
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line_section = section
        if line[:3].upper() == "SB:":
            line, line_section = line[3:].strip(), "sideboard"
        m = _LINE.match(line)
        if not m:
            header = _HEADER.match(line)
            key = header.group(1).strip().lower() if header else None
            if key in SECTIONS:
                section = SECTIONS[key]
            elif not line.startswith(("//", "#")):
                unparsed.append(raw)
            continue
        # Archidekt appends flags to categories: "Commander{top}", "Maybeboard{noDeck}{noPrice}".
        cats = [re.sub(r"\{[^}]*\}", "", c).strip() for c in (m["cats"] or "").split(",")]
        cats = [c for c in cats if c]
        for c in cats:
            if c.lower() in SECTIONS and SECTIONS[c.lower()] != MAIN:
                line_section = SECTIONS[c.lower()]
                break
        lines.append(DeckLine(
            quantity=int(m["qty"]),
            name=m["name"].strip(),
            set_code=(m["set"] or m["bset"]).lower() if (m["set"] or m["bset"]) else None,
            collector_number=m["num"],
            finish={"F": Finish.FOIL, "E": Finish.ETCHED}.get(m["finish"] or "", Finish.NONFOIL),
            section=line_section,
            categories=cats,
        ))
    return Decklist(lines, name=name, unparsed=unparsed)


def parse_url(url: str) -> tuple[str, str] | None:
    """Recognise a deck URL. Returns ``("archidekt", "123456")``, ``("moxfield", "abcDEF")`` or ``None``.

    Archidekt decks can be fetched with :class:`mtg_toolkits.archidekt.ArchidektClient`.
    Moxfield has no public API (it asks third parties to get permission first),
    so for Moxfield decks ask the user to paste the text export instead.
    """
    parsed = urlparse(url.strip() if "//" in url else "https://" + url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    parts = [p for p in parsed.path.split("/") if p]
    if host == "archidekt.com":
        if len(parts) >= 2 and parts[0] == "decks" and parts[1].isdigit():
            return "archidekt", parts[1]
        if len(parts) >= 3 and parts[:2] == ["api", "decks"] and parts[2].isdigit():
            return "archidekt", parts[2]
    if host == "moxfield.com" and len(parts) >= 2 and parts[0] == "decks":
        return "moxfield", parts[1]
    return None
