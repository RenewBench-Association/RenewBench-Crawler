"""Fuel utilities.

Utility functions for handling fuel type-related logic.
"""

import re
from functools import lru_cache

from rbc.coordinates.utils.values import normalize_name

FUEL_UNKNOWN: frozenset[str] = frozenset({"unknown", "none", "missing"})

# todo: are these synonym definitions all appropriate or are some (waste/storage) too much?
FUEL_TOKEN_SYNONYMS: dict[str, str] = {
    "diesel": "oil",
    "lignite": "coal",
    "lng": "gas",
    "product": "waste",
    "landfill": "waste",
    "battery": "storage",
    "photovoltaic": "solar",
    "hydroelectric": "hydro",
}
FUEL_STOPWORDS: frozenset[str] = frozenset(["fuel"])


def classify_fueltype_match(sysop_type: str | None, loc_type: str | None) -> str:
    """Classify fueltype compatibility of an operator's EGE and its matched locator EGE.

    tokenize_fuel transforms the provided types into normalized lists of lowercase tokens,
    where empty values are handled gracefully (`None` -> `''`). These are compared to one
    another as sets to define their relationship (compatibility).

    Args:
        sysop_type: Canonical fuel type from the operator's EGE (e.g. ``"wind"``).
        loc_type: Fuel type string from the matched locator's EGE (e.g. ``"Wind"``).

    Returns:
        str: Compatibility of the two EGS's fuel types.
            ``"unknown"``    — one or both are missing or defined as unknown.
            ``"exact"``      — both normalize to an identical token sets.
            ``"compatible"`` — at least one token in both sets is identical.
            ``"mismatch"``   — clearly different fuel types.
    """
    # build tokens to compare
    sysop_fuel_toks = set(_tokenize_fuel(sysop_type))
    loc_fuel_toks = set(_tokenize_fuel(loc_type))

    if (
        not sysop_fuel_toks
        or not loc_fuel_toks
        or sysop_fuel_toks <= FUEL_UNKNOWN
        or loc_fuel_toks <= FUEL_UNKNOWN
    ):  # e.g. either is missing ({}) or consists of only unknown toks ({'missing', 'none'})
        return "unknown"

    if sysop_fuel_toks == loc_fuel_toks:  # e.g. {'wind'} vs {'wind'}
        return "exact"

    if sysop_fuel_toks & loc_fuel_toks:  # e.g. {'fossil', 'gas'} vs {'natural', 'gas'}
        return "compatible"

    if sysop_fuel_toks & FUEL_UNKNOWN or loc_fuel_toks & FUEL_UNKNOWN:
        return "unknown"  # e.g. {'none'} vs {'gas'}

    return "mismatch"  # e.g. {'fossil', 'oil'} vs {'offshore', 'wind'}


def is_fueltype_compatible(sysop_type: str | None, loc_type: str | None) -> bool:
    """Validate if the operator EGE's fuel type matches the locator EGE's fuel type.

    Args:
        sysop_type: Fuel type of EGE from system operator data.
        loc_type: Fuel type of EGE from locator database.

    Returns:
        bool: True if types are compatible, False otherwise.
    """
    compatibility = classify_fueltype_match(sysop_type, loc_type)
    if compatibility == "mismatch":
        return False
    else:
        return True


@lru_cache(maxsize=1024)
def _tokenize_fuel(value: str | None) -> tuple[str, ...]:
    """Normalize a fuel label, then split it into individual, comparable words (tokens).

    The re search pattern finds individual string words; normalizing implements .lower().
    Words are unified through the synonym dict (``FUEL_TOKEN_SYNONYMS``) and some removed
    if they have no meaning and might cause a false match (e.g. "fuel").

    Args:
        value (str | None): Fuel label to split.

    Returns:
        tuple[str]: Tuple of individual words (tokens) in fuel label, in correct order.
    """
    tokens: list[str] = re.findall(r"[a-z]+", normalize_name(value))
    return tuple(
        [FUEL_TOKEN_SYNONYMS.get(t, t) for t in tokens if t not in FUEL_STOPWORDS]
    )
