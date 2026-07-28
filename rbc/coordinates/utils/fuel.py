"""Fuel utilities.

Utility functions for handling fuel type-related logic.
"""

import pandas as pd

from rbc.energy.entsoe.mappings import FUELTYPE_MAPPINGS


def normalize_fueltype(value: str | None) -> str:
    """Normalize fuel type strings/codes to comparable lowercase labels.

    Args:
        value (str | None): Fuel type string/code to normalize.
    """
    if value is None or pd.isna(value):
        return ""

    raw = str(value).strip()
    mapped = FUELTYPE_MAPPINGS.get(raw, raw)
    return str(mapped).lower().strip()


def is_fueltype_compatible(eg_type: str | None, pp_type: str | None) -> bool:
    """Validate if the eg fuel type matches the pp database fuel type.

    Handles basic string cleaning and empty values gracefully.

    Args:
        eg_type: Fuel type from energy generation data.
        pp_type: Fuel type from power plant database.

    Returns:
        True if types are compatible, False otherwise.
    """
    if pd.isna(eg_type) or pd.isna(pp_type):
        return True  # If one dataset lacks a type, we pass it but remain cautious

    eg_clean = normalize_fueltype(eg_type)
    pp_clean = normalize_fueltype(pp_type)

    # Check if one contains the other
    return eg_clean in pp_clean or pp_clean in eg_clean


def classify_fueltype_match(eg_type: str | None, pp_type: str | None) -> str:
    """Classify the fuel-type agreement between an eg plant and the pp information.

    Args:
        eg_type: Canonical fuel type from the energy production data (e.g. ``"wind"``).
        pp_type: Fuel type string from PPM / OSMPP (e.g. ``"Wind"``).

    Returns:
        ``"exact"``      — both normalize to the same label.
        ``"compatible"`` — one contains the other, or one side is missing.
        ``"mismatch"``   — clearly different fuel types.
    """
    eg = normalize_fueltype(eg_type)
    pp = normalize_fueltype(pp_type)
    if not eg or not pp:
        return "compatible"
    if eg == pp:
        return "exact"
    if eg in pp or pp in eg:
        return "compatible"
    return "mismatch"
