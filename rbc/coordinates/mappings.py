"""Mappings used by the coordinate locator orchestrator.

This module contains operator metadata with defining attributes for running the pipelines
and other global parameters for coordinate finding. They are mainly used by the pipeline
modules and utility helpers.
"""

from typing import NotRequired, TypedDict

from rbc.energy.entsoe.mappings import FUELTYPE_CODE_MAPPINGS


class OperatorInfo(TypedDict):
    """Define parameters describing operator info, with typesetting and which are required."""

    country: str
    entity_col: str
    needs_coordinates: bool
    code_col: NotRequired[str]
    fuel_col: NotRequired[str]
    fuel_mapping: NotRequired[dict[str, str]]
    pipeline: NotRequired[str]


# Map: Operator name → defining details for location finding (e.g. data column names)
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
        country="Türkiye", entity_col="powerPlantName", needs_coordinates=True
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
        code_col="id_ons",
        fuel_col="nom_tipousina",
        needs_coordinates=True,
    ),
    "rei": OperatorInfo(country="Japan", entity_col="", needs_coordinates=False),
    "taipower": OperatorInfo(
        country="Taiwan", entity_col="name", fuel_col="fueltype", needs_coordinates=True
    ),
}

# Map: Country codes (ISO3166-1:alpha-2) → OSM relation IDs (from update_osm_relation_ids.py)
COUNTRY_OSM_RELATION_ID_MAP: dict[str, int] = {
    "AL": 53292,
    "AT": 16239,
    "AU": 80500,
    "BA": 2528142,
    "BE": 52411,
    "BG": 186382,
    "BR": 59470,
    "CA": 1428125,
    "CH": 51701,
    "CL": 167454,
    "CZ": 51684,
    "DE": 51477,
    "DK": 50046,
    "EE": 79510,
    "ES": 1311341,
    "FI": 54224,
    "FR": 2202162,
    "GB": 62149,
    "GE": 28699,
    "GR": 192307,
    "HU": 21335,
    "IE": 62273,
    "IT": 365331,
    "JP": 382313,
    "LT": 72596,
    "LV": 72594,
    "MD": 58974,
    "ME": 53296,
    "MK": 53293,
    "NL": 2323309,
    "NO": 2978650,
    "NZ": 556706,
    "PL": 49715,
    "PT": 295480,
    "RO": 90689,
    "RS": 1741311,
    "SE": 52822,
    "SI": 218657,
    "SK": 14296,
    "TR": 174737,
    "TW": 449220,
    "US": 148838,
    "UY": 287072,
    "XK": 2088990,
}

# Set: Tokens that indicate a generic name/suffix rather than a matchable EGE name.
# Use to strip away unhelpful content for proper name matching (e.g. "Sloe unit 20" → "Sloe").
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


# Map: EGE fuel type abbreviations / non-english terms → English equivalents.
# Apply before fuzzy matching to properly resolve to the correct tokens.
# E.g. ENTSOE's "HE_CAPLJINA_G1" & OSM's "Hidroelektrana Čapljina" → same "hydro" token
PLANT_NAME_EXPANSIONS: dict[str, str] = {
    # --- Abbreviations that appear as first token - used in ENTSO-E EGE codes/names ---
    "he": "hydroelectric",
    "te": "thermal",
    "ve": "wind",
    "fe": "solar",
    "ne": "nuclear",
    "re": "pumped hydro",
    "bess": "bess battery",  # add "battery" since OSM/GEM/PPM often have that label
    # --- Full non-english names (Bosnian / Croatian / Serbian) - used in OSM ---
    "hidroelektrana": "hydroelectric",
    "hidroelektrane": "hydroelectric",
    "termoelektrana": "thermal",
    "termoelektrane": "thermal",
    "vjetroelektrana": "wind",
    "vjetroelektrane": "wind",
    "fotonaponska": "solar",
    "nuklearna": "nuclear",
    "reverzibilna": "pumped hydro",
    "elektrana": "power plant",
    "elektrane": "power plant",
}


# Map: Country codes → country-specific additions/overrides for PLANT_NAME_EXPANSIONS
# Add on top to refine ambiguous/incorrect per-country tokens affecting others.
COUNTRY_PLANT_NAME_EXPANSIONS: dict[str, dict[str, str]] = {
    "EE": {
        # Estonian power plant terms (ENTSO-E uses these generic terms)
        "elektrijaam": "power plant",
        "elektrijaama": "power plant",
        "elektrijaamad": "power plant",
        # Additional translations for cross-database matching (OSM specifies type)
        "soojuselektrijaam": "thermal power plant",
        "soojus": "thermal",
        "balti": "balti",
        "eesti": "eesti",
        "ej": "power plant elektrijaam",  # abbreviation
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
