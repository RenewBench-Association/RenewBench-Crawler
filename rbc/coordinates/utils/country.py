"""Country utilities.

Utility functions for handling country-related logic.
"""

import re

from rbc.coordinates.utils.values import strip_lower_str, strip_str


def normalize_country_for_matching(country: str | None) -> str | None:
    """Normalize a country name to match PPM database country names.

    This handles zone-specific country aliases (e.g., 'Germany (TransnetBW)',
    'Great Britain / National Grid') and maps them to their base country names
    (e.g., 'Germany', 'United Kingdom') as used in PPM.

    Args:
        country: Country name that may include zone-specific suffixes.

    Returns:
        Normalized country name or provided "country" value if no normalization possible.
    """
    country = strip_str(country)
    if country is None:
        return None

    # 1. Extract base country name by removing suffixes (e.g. "Germany (tennet)" -> "Germany")
    base_country = re.sub(r"\s*\([^)]*\)\s*$", "", country).strip()

    # 2. Handle slash-separated names (e.g. "Great Britain / National Grid" -> "Great Britain"
    if "/" in base_country:
        parts = [part.strip() for part in base_country.split("/")]
        base_country = parts[0] if parts else base_country

    # 3. Handle known names with special mapping (e.g. "United Kingdom" vs "Great Britain")
    alias_mappings = {
        "great britain": "united kingdom",
        "gb": "united kingdom",
    }
    base_country_lower = base_country.lower()
    if base_country_lower in alias_mappings:
        return alias_mappings[base_country_lower]

    # 4. Clean up any remaining artifacts & return
    base_country = base_country.strip()
    if base_country:
        return base_country

    return country


def get_ppm_country_name(country: str | None) -> str | None:
    """Get a country name as it appears in PPM database.

    This handles when PPM uses slightly different country names than what our metadata has.

    Args:
        country (str | None): Country name that may include zone-specific suffixes.

    Returns:
        PPM country name or provided "country" if no adaptation necessary/possible.
    """
    if not country:
        return None

    # Map known aliases to PPM country names
    ppm_country_aliases = {
        "estonia": "Estonia",
        "ee": "Estonia",
        "switzerland": "Switzerland",
        "ch": "Switzerland",
        "germany": "Germany",
        "de": "Germany",
        "france": "France",
        "fr": "France",
    }

    country_lower = strip_lower_str(country)
    return ppm_country_aliases.get(country_lower, country)
