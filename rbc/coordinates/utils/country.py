"""Country utilities.

Utility functions for handling country-related logic.
"""

import re

import country_converter as coco
import pandas as pd
from loguru import logger

from rbc.coordinates.utils.values import strip_str

ALIAS_MAPPINGS: dict[str, str] = {
    "great britain": "United Kingdom",
    "northern ireland": "United Kingdom",
    "czech republic": "Czechia",
}


def normalize_operator_country_name(country: str | None) -> str | None:
    """Normalize a country name to enable matching (operators <-> locator sources).

    This handles any country aliases with special characters (e.g. 'Germany (Tennet)', 'Great
    Britain / Grid') or different region-to-country definitions (e.g. NI belongs to UK) and
    maps them to their true country names (e.g. 'Germany', 'United Kingdom').

    Args:
        country (str | None): Operator country name that may include extra symbols.

    Returns:
        country (str | None): Titled, normalized country name or provided one if
            normalization failed or None if country is None.
    """
    country = strip_str(country)
    if not country:
        return None

    # 1. Extract base country name by removing special characters (brackets, backslashes)
    base_country = re.sub(r"\s*\([^)]*\)\s*$", "", country).strip()
    base_country = base_country.split("/")[0].strip()

    # 2. Apply special mapping where required (e.g. "Great Britain" -> "United Kingdom")
    base_country = ALIAS_MAPPINGS.get(base_country.lower(), base_country)

    # 3. Clean up any remaining artifacts & return
    if base_country:
        return base_country.strip()

    return country.strip()


def normalize_locator_countries(
    df: pd.DataFrame, country_col: str = "Country"
) -> pd.DataFrame:
    """Normalize a dataframe's country values to enable matching.

    Convert to coco's titled 'short_name' versions (where possible) and apply the
    ALIAS_MAPPING to align with operator countries.

    Args:
        df (pd.DataFrame): Locator dataframe containing country column to normalize.
        country_col (str, Optional): Name of country column. Defaults to "Country".

    Returns:
        pd.DataFrame: Updated dataframe with normalized country values.
    """
    if country_col not in df.columns:
        logger.warning(
            f"Country column '{country_col}' not found in dataframe. No normalization!"
        )
        return df

    unique_countries = df[country_col].unique()
    short_countries: list[str] = coco.convert(
        names=list(unique_countries), to="short_name"
    )
    normalized_country_mapping: dict[str, str] = {}

    for original, short in zip(unique_countries, short_countries):
        if short == "not found":
            logger.warning(
                f"Country '{original}' could not be interpreted by the Python country "
                f"converter! Keeping it as is..."
            )
            short = original

        normalized_country_mapping[original] = ALIAS_MAPPINGS.get(short.lower(), short)

    # rename values in "country_col"
    df = df.copy()
    df[country_col] = df[country_col].map(normalized_country_mapping)
    return df
