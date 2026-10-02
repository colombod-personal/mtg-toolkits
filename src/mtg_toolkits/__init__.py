"""Tools for working with Magic: The Gathering data sources.

- :mod:`mtg_toolkits.scryfall` -- card text, attributes, images and daily prices
- :mod:`mtg_toolkits.archidekt` -- public decks (unofficial, undocumented API)
- :mod:`mtg_toolkits.dragonshield` -- Dragon Shield Card Manager CSV import/export
- :mod:`mtg_toolkits.formats` -- detect/read/write collection files across apps (migration)
- :mod:`mtg_toolkits.moxfield` -- Moxfield collection CSV import/export (Moxfield has no public API)
- :mod:`mtg_toolkits.normalize` -- set codes, collector numbers and locale-tolerant numbers, as matching uses them
"""

from .models import CollectionEntry, Condition, Finish
from .normalize import normalize_collector_number, normalize_set_code, parse_number, parse_quantity, set_alias_map

__version__ = "0.2.0"
__all__ = ["CollectionEntry", "Condition", "Finish", "normalize_collector_number", "normalize_set_code",
           "parse_number", "parse_quantity", "set_alias_map", "__version__"]
