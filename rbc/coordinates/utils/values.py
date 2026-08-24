# rbc/coordinates/utils/values.py
"""Value utilities.

Utility functions for handling string-conversion related logics shared by modules,
especially normalizers (tokenizer.*, country.*, map.*).
"""

import re
import unicodedata

import pandas as pd

# Map for normalize_name(): Atomic letters → ASCII equivalents.
# NFKD only decomposes base+diacritic pairs, so this helps interpret e.g.: "Skærbækværket"
_TRANSLITERATIONS = str.maketrans(
    {
        "æ": "ae",
        "œ": "oe",
        "ø": "o",
        "ł": "l",
        "ß": "ss",
        "đ": "d",
        "ð": "d",
        "þ": "th",
    }
)


def normalize_name(value: str | None) -> str:
    """Normalize the provided value for robust cross-source matching.

    Lowercase, transliterate atomic non-ASCII letters, strip diacritics, replace
    non-alphanumeric runs with a single space, collapse whitespace.

    Args:
        value (str): The value to normalize.

    Returns:
        Normalized string value.
    """
    text = strip_lower_str(value)
    if not text:
        return ""

    text = text.translate(_TRANSLITERATIONS)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


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
