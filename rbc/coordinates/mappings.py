"""Mappings used by the coordinate locator orchestrator.

This module contains operator metadata with defining attributes for running the pipelines
and other global parameters for coordinate finding. They are mainly used by the pipeline
modules and utility helpers.
"""

from typing import NotRequired, TypedDict

from rbc.energy.entsoe.mappings import EGE_NAME_TRANSLATIONS as ENTSOE_NAME_TRANSLATIONS
from rbc.energy.entsoe.mappings import FUELTYPE_CODE_MAPPINGS as ENTSOE_FUEL_MAPPINGS
from rbc.energy.ons.mappings import (
    EGE_NAME_TRANSLATIONS as ONS_NAME_TRANSLATIONS,
)
from rbc.energy.ons.mappings import (
    FUELTYPE_MAPPING as ONS_FUEL_MAPPINGS,
)


# ---------------------------------------------------------------------------
# Systems Operator Definitions (energy sources)
# ---------------------------------------------------------------------------
class OperatorInfo(TypedDict):
    """Define parameters describing operator info, with typesetting and which are required."""

    needs_coordinates: bool
    country: str
    entity_col: str
    entity_mapping: NotRequired[dict[str, str] | dict[str, dict[str, str]]]
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
        entity_mapping=ENTSOE_NAME_TRANSLATIONS,
        code_col="time_series.mkt_psrtype.power_system_resources.m_rid.value",
        fuel_col="time_series.mkt_psrtype.psr_type",
        fuel_mapping=ENTSOE_FUEL_MAPPINGS,
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
        entity_mapping=ONS_NAME_TRANSLATIONS,
        code_col="id_ons",
        fuel_col="nom_tipousina",
        fuel_mapping=ONS_FUEL_MAPPINGS,
        needs_coordinates=True,
    ),
    "rei": OperatorInfo(country="Japan", entity_col="", needs_coordinates=False),
    "taipower": OperatorInfo(
        country="Taiwan", entity_col="name", fuel_col="fueltype", needs_coordinates=True
    ),
}

# ---------------------------------------------------------------------------
# Country Definitions
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Matching Definitions (name, fueltype)
# ---------------------------------------------------------------------------
# Set: Tokens that indicate a generic EGE-related term to be removed in name matching. Uses:
# - remove unhelpful content from "normal" names (e.g. 'Sloe unit 20' → ['Sloe']).
# - safely remove from "glued" names (e.g. 'ENGURIUNIT_5' → ['enguri', '5'])
GENERIC_UNIT_TOKENS: frozenset[str] = frozenset(
    {
        "unit",
        "units",
        "block",
        "bloco",
        "blok",
        "conj.",
        "conjunto",
        "group",
        "groep",
        "generator",
        "gen",
        "g",
    }
)

# Set: Tokens that indicate a generic energy-related term instead of a matchable name. Uses:
# - reduce weight of generic terms (e.g. 'Sloe station' → {'sloe': 1.0, 'station': 0.x}).
GENERIC_ENERGY_TOKENS: frozenset[str] = frozenset(
    {
        "power",
        "plant",
        "park",
        "station",
        "farm",
        "project",
        "energy",
        "electric",
        "house",
        # fueltypes
        "wind",
        "solar",
        "nuclear",
        "hydro",
        "hydroelectric",
        "biomass",
        "thermal",
        "coal",
        "oil",
        "gas",
        "waste",
    }
)
