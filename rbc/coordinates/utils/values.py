# rbc/coordinates/utils/values.py
"""Value utilities.

Utility functions for handling string-conversion related logics shared by modules,
especially normalizers (tokenizer.normalize_name, fuel.normalize_fueltype, country.*, map.*).
"""

import pandas as pd


def is_missing(value: object) -> bool:
    """Check whether a scalar is None, NaN, or blank after stripping.

    Args:
        value (object): Scalar to check.

    Returns:
        bool: Whether the scalar is None, NaN, or blank after stripping.
    """
    if value is None:
        return True

    # include is_scalar as pd.isna() returns bool array for list/dict/ndarray instead of T/F
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return True

    return not str(value).strip()


def strip_str(value: object) -> str | None:
    """Return `value` as a stripped string, or None if missing.

    Args:
        value (object): Value to be stripped.

    Returns:
        str | None: Stripped string or None if value is missing/blank.
    """
    return None if is_missing(value) else str(value).strip()


def strip_lower_str(value: object) -> str:
    """Return `value` as a stripped, lowercased string, or "" if missing.

    Args:
        value (object): Value to be stripped.

    Returns:
        str: Stripped string or empty string if value is missing.
    """
    return "" if is_missing(value) else str(value).strip().lower()
