"""Tools for working with Magic: The Gathering data sources.

- :mod:`mtg_toolkits.scryfall` -- card text, attributes, images and daily prices
- :mod:`mtg_toolkits.archidekt` -- public decks (unofficial, undocumented API)
- :mod:`mtg_toolkits.dragonshield` -- Dragon Shield Card Manager CSV import/export
"""

from .models import CollectionEntry, Condition, Finish

__version__ = "0.1.0"
__all__ = ["CollectionEntry", "Condition", "Finish", "__version__"]
