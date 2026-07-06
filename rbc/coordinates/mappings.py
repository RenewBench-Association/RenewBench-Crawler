"""Mappings used by the coordinate locator orchestrator.

This module contains operator metadata required by
rbc.coordinates.orchestrator.CoordinateLocator.

Only ENTSO-E field names are fully validated in this minimal reconstruction.
All other operators keep the same key structure with placeholder columns so the
expected mapping shape exists while follow-up validation is performed.
"""

# TODO: This is a minimal working version of the mapping module only, Elena did not upload the mapping file to the repo :D. So this is a gestimated version of the mapping file.

from __future__ import annotations

# Mapping of power plant type abbreviations and local language full names to
# canonical English equivalents. Applied before fuzzy matching so that
# e.g. ENTSO-E coded names like "HE_CAPLJINA_G1" and OSM names like
# "Hidroelektrana Čapljina" both resolve to the same "hydroelectric" token.
#
# Keys are lowercase, matching normalized (diacritic-stripped) forms.
PLANT_NAME_EXPANSIONS: dict[str, str] = {
    # --- Abbreviations used in ENTSO-E unit codes (appear as first token) ---
    "he": "hydroelectric",  # Hidroelektrana
    "te": "thermal",  # Termoelektrana
    "ve": "wind",  # Vjetroelektrana
    "fe": "solar",  # Fotoelektrana / Fotonaponska elektrana
    "ne": "nuclear",  # Nuklearna elektrana
    "re": "pumped hydro",  # Reverzibilna elektrana (pumped storage)
    # --- Bosnian / Croatian / Serbian full names (appear in OSM) ---
    "hidroelektrana": "hydroelectric",
    "hidroelektrane": "hydroelectric",
    "termoelektrana": "thermal",
    "termoelektrane": "thermal",
    "vjetroelektrana": "wind",
    "vjetroelektrane": "wind",
    "fotonaponska": "solar",
    "nuklearna": "nuclear",
    "elektrana": "power plant",
    "elektrane": "power plant",
    # --- Battery storage: keep the original abbreviation but also append
    # "battery" as an additional keyword, since OSM/GEM/PPM commonly label
    # storage sites "Battery ..." rather than "BESS ..." (e.g. ENTSO-E/local
    # names like "BESS Andes" vs. OSM's "Andes Battery Storage").
    "bess": "bess battery",
}


# Country-specific additions/overrides for PLANT_NAME_EXPANSIONS, keyed by ISO
# 3166-1 alpha-2 country code (see COUNTRY_ISO2_MAP below). Applied on top of
# the global PLANT_NAME_EXPANSIONS so that ambiguous or otherwise-incorrect
# generic tokens can be refined per country without affecting other countries.
COUNTRY_PLANT_NAME_EXPANSIONS: dict[str, dict[str, str]] = {
    "EE": {
        # ENTSO-E unit names use the generic Estonian word for "power plant"
        # (e.g. "Balti Elektrijaam"), while OSM names the same stations with the
        # more specific "soojuselektrijaam" ("thermal power plant", e.g. "Balti
        # Soojuselektrijaam", "Eesti Soojuselektrijaam"). Expanding to the
        # specific term lets fuzzy matching bridge the two sources.
        "elektrijaam": "soojuselektrijaam",
        "elektrijaama": "soojuselektrijaam",
        "elektrijaamad": "soojuselektrijaam",
    },
}


# Tokens that indicate a unit/block number suffix rather than a plant-specific
# name. Used by the strip-numeric fallback matcher to reduce e.g.
# "Sloecentrale unit 20" → "Sloecentrale" so it matches the OSM station entry.
GENERIC_UNIT_TOKENS: frozenset[str] = frozenset(
    {
        "unit",
        "units",
        "block",
        "blok",
        "group",
        "groep",
        "generator",
        "gen",
        "g",
    }
)


# Mapping from country name aliases (lowercase) used across ENTSO-E and other
# operator datasets to ISO 3166-1 alpha-2 country codes.
COUNTRY_ISO2_MAP: dict[str, str] = {
    "albania": "AL",
    "argentina": "AR",
    "australia": "AU",
    "austria": "AT",
    "belgium": "BE",
    "bosnia and herzegovina": "BA",
    "bulgaria": "BG",
    "canada": "CA",
    "chile": "CL",
    "czech republic": "CZ",
    "denmark": "DK",
    "estonia": "EE",
    "finland": "FI",
    "france": "FR",
    "georgia": "GE",
    "germany": "DE",
    "germany (50hertz)": "DE",
    "germany (amprion)": "DE",
    "germany (tennet)": "DE",
    "germany (transnetbw)": "DE",
    "great britain / national grid": "GB",
    "greece": "GR",
    "hungary": "HU",
    "ireland / sem(eirgrid)": "IE",
    "italy": "IT",
    "kosovo": "XK",
    "latvia": "LV",
    "lithuania": "LT",
    "mexico": "MX",
    "moldova": "MD",
    "montenegro": "ME",
    "netherlands": "NL",
    "north macedonia": "MK",
    "northern ireland / sem(soni)": "GB",
    "norway": "NO",
    "poland": "PL",
    "portugal": "PT",
    "romania": "RO",
    "serbia": "RS",
    "slovakia": "SK",
    "slovenia": "SI",
    "spain": "ES",
    "sweden": "SE",
    "switzerland": "CH",
    "taiwan": "TW",
    "turkey": "TR",
    "united kingdom": "GB",
    "united states": "US",
}


OPERATOR_METADATA: dict[str, dict[str, str | None]] = {
    "adme": {
        "country": "Argentina",
        "entity_col": "",
        "code_col": None,
        "fuel_col": None,
    },
    "aemo": {
        "country": "Australia",
        "entity_col": "",
        "code_col": None,
        "fuel_col": None,
    },
    "aeso": {
        "country": "Canada",
        "entity_col": "",
        "code_col": None,
        "fuel_col": None,
    },
    "cen": {
        "country": "Chile",
        "entity_col": "",
        "code_col": None,
        "fuel_col": None,
    },
    "eat": {
        "country": "Taiwan",
        "entity_col": "",
        "code_col": None,
        "fuel_col": None,
    },
    "eia": {
        "country": "United States",
        "entity_col": "respondent-name",
        "code_col": "respondent",
        "fuel_col": "fueltype",
    },
    "entsoe": {
        "country": "Europe",
        "entity_col": "time_series.mkt_psrtype.power_system_resources.name",
        "code_col": "time_series.mkt_psrtype.power_system_resources.m_rid.value",
        "fuel_col": "time_series.mkt_psrtype.psr_type",
    },
    "epias": {
        "country": "Turkey",
        "entity_col": "",
        "code_col": None,
        "fuel_col": None,
    },
    "ieso": {
        "country": "Canada",
        "entity_col": "",
        "code_col": None,
        "fuel_col": None,
    },
    "ons": {
        "country": "United Kingdom",
        "entity_col": "",
        "code_col": None,
        "fuel_col": None,
    },
    "rei": {
        "country": "Mexico",
        "entity_col": "",
        "code_col": None,
        "fuel_col": None,
    },
    "taipower": {
        "country": "Taiwan",
        "entity_col": "",
        "code_col": None,
        "fuel_col": None,
    },
}
