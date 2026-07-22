"""Mappings used by the coordinate locator orchestrator.

This module contains operator metadata required by
rbc.coordinates.orchestrator.CoordinateLocator.

Only ENTSO-E field names are fully validated in this minimal reconstruction.
All other operators keep the same key structure with placeholder columns so the
expected mapping shape exists while follow-up validation is performed.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from rbc.energy.entsoe.mappings import FUELTYPE_CODE_MAPPINGS

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
        "elektrijaam": "power plant",
        "elektrijaama": "power plant",
        "elektrijaamad": "power plant",
        # Additional Estonian to English translations for cross-database matching
        "soojuselektrijaam": "thermal power plant",
        "soojus": "thermal",
        "balti": "balti",
        "eesti": "eesti",
        "ej": "power plant elektrijaam",  # Estonian abbreviation for Elektrijaam
    },
    "CH": {
        # Swiss German/French/Italian power plant terms
        "kraftwerk": "power plant",
        "centrale": "power plant",
        "central": "power plant",
        "elettrica": "electric power",
        "électrique": "electric power",
        "hydro": "hydroelectric hydro",
        "thermique": "thermal power",
    },
    "DE": {
        # German power plant terms
        "kraftwerk": "power plant",
        "heizkraftwerk": "power plant heating",
        "gaskraftwerk": "power plant gas",
        "kohlekraftwerk": "power plant coal",
        "wasserkraftwerk": "power plant hydro hydroelectric",
        "windkraftwerk": "power plant wind",
        "biomassekraftwerk": "power plant biomass",
    },
    "FR": {
        # French power plant terms
        "centrale": "power plant",
        "central": "power plant",
        "électrique": "electric power",
        "thermique": "thermal power",
        "nucléaire": "nuclear power",
        "hydroélectrique": "hydroelectric hydro",
    },
    "ES": {
        # Spanish power plant terms
        "central": "power plant",
        "eléctrica": "electric power",
        "térmica": "thermal power",
        "hidroeléctrica": "hydroelectric hydro",
        "eólica": "wind power",
    },
    "IT": {
        # Italian power plant terms
        "centrale": "power plant",
        "elettrica": "electric power",
        "termica": "thermal power",
        "idroelettrica": "hydroelectric hydro",
        "eolica": "wind power",
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


class OperatorInfo(TypedDict):
    """Class for defining operator detail parameters and their types."""

    country: str
    entity_col: str
    needs_coordinates: bool
    code_col: NotRequired[str]
    fuel_col: NotRequired[str]
    fuel_mapping: NotRequired[dict[str, str]]
    pipeline: NotRequired[str]


OPERATOR_METADATA: dict[str, OperatorInfo] = {
    "adme": OperatorInfo(country="Uruguay", entity_col="", needs_coordinates=True),
    "aemo": OperatorInfo(
        country="Australia",
        entity_col="unit_code",
        fuel_col="unit_fueltech_id",
        needs_coordinates=False,
    ),
    "aeso": OperatorInfo(
        country="Canada",
        entity_col="Asset Name",
        fuel_col="Fuel Type",
        needs_coordinates=True,
    ),
    "cen": OperatorInfo(
        country="Chile",
        entity_col="central",
        fuel_col="tipo_tecnologia",
        code_col="id_central",
        needs_coordinates=True,
    ),
    "eat": OperatorInfo(
        country="New Zealand",
        entity_col="gen_code",
        fuel_col="fuel_code",
        needs_coordinates=True,
    ),
    "eia": OperatorInfo(
        country="United States",
        entity_col="respondent-name",
        code_col="respondent",
        fuel_col="fueltype",
        needs_coordinates=False,
    ),
    "entsoe": OperatorInfo(
        country="Europe",
        entity_col="time_series.mkt_psrtype.power_system_resources.name",
        code_col="time_series.mkt_psrtype.power_system_resources.m_rid.value",
        fuel_col="time_series.mkt_psrtype.psr_type",
        fuel_mapping=FUELTYPE_CODE_MAPPINGS,
        pipeline="entsoe",
        needs_coordinates=True,
    ),
    "epias": OperatorInfo(
        country="Turkey", entity_col="powerPlantName", needs_coordinates=True
    ),
    "ieso": OperatorInfo(
        country="Canada",
        entity_col="Generator",
        fuel_col="Fuel Type",
        needs_coordinates=False,
    ),
    "ons": OperatorInfo(
        country="Brazil",
        entity_col="nom_usina",
        fuel_col="nom_tipousina",
        code_col="id_ons",
        needs_coordinates=True,
    ),
    "rei": OperatorInfo(country="Japan", entity_col="", needs_coordinates=False),
    "taipower": OperatorInfo(
        country="Taiwan", entity_col="name", fuel_col="fueltype", needs_coordinates=True
    ),
}
