"""BARRA variable mappings and metadata.

Constants for BARRA reanalysis variables and region configurations.
"""

# BARRA-R2/RE2 surface-level variables (1hr frequency)
SURFACE_VARIABLES_R2_RE2 = {
    "tas",  # 2m air temperature
    "tasmean",  # Mean 2m air temperature
    "tasmax",  # Max 2m air temperature
    "tasmin",  # Min 2m air temperature
    "uas",  # Eastward near-surface wind
    "uasmean",  # Mean eastward near-surface wind
    "uasmax",  # Max eastward near-surface wind
    "vas",  # Northward near-surface wind
    "vasmean",  # Mean northward near-surface wind
    "vasmax",  # Max northward near-surface wind
    "sfcWind",  # Near-surface wind speed
    "ps",  # Surface air pressure
    "psl",  # Sea level pressure
    "pr",  # Total precipitation
    "hurs",  # Near-surface relative humidity
    "huss",  # Near-surface specific humidity
    "rsds",  # Surface downwelling shortwave radiation
    "rsus",  # Surface upwelling shortwave radiation
    "rlds",  # Surface downwelling longwave radiation
    "rlus",  # Surface upwelling longwave radiation
    "hfls",  # Surface latent heat flux
    "hfss",  # Surface sensible heat flux
}

# BARRA-C2 surface-level variables (1hr frequency, includes convective extras)
SURFACE_VARIABLES_C2 = SURFACE_VARIABLES_R2_RE2 | {
    "flashrate",  # Lightning flash rate
    "fogfraction",  # Fog fraction at 1.5m
    "visibility",  # Visibility at 1.5m
    "wsgs",  # Wind gust speed
    "prga",  # Graupel sediment rate
    "prra",  # Large scale rainfall rate
    "prsnmax",  # Hourly maximum snowfall rate
    "prhmax",  # Monthly mean daily maximum hourly precipitation
    "prmax",  # Hourly maximum precipitation
    "prsn",  # Snowfall flux
    "twiso",  # Isobaric wet-bulb temperature
    "twpse",  # Pseudo wet-bulb temperature
}

# Atmospheric vertical level variables (pressure levels)
PRESSURE_LEVEL_VARIABLES_R2_RE2 = {
    "ta",  # Air temperature at pressure levels
    "ua",  # Eastward wind at pressure levels
    "va",  # Northward wind at pressure levels
    "hus",  # Specific humidity at pressure levels
    "wap",  # Vertical velocity (pressure) at pressure levels
    "zg",  # Geopotential height at pressure levels
}

PRESSURE_LEVEL_VARIABLES_C2 = PRESSURE_LEVEL_VARIABLES_R2_RE2 | {
    "wa",  # Upward air velocity at pressure levels
}

# Vertically integrated variables
INTEGRATED_VARIABLES_R2_RE2 = {
    "clt",  # Total cloud cover
    "clh",  # High cloud fraction
    "clm",  # Mid-level cloud fraction
    "cll",  # Low cloud fraction
    "prw",  # Water vapor path
    "clwvi",  # Condensed water path
    "clivi",  # Ice water path
}

INTEGRATED_VARIABLES_C2 = INTEGRATED_VARIABLES_R2_RE2 | {
    "maxcolrefl",  # Maximum radar reflectivity in column
    "maxcolwa",  # Maximum vertical wind speed in column
    "helicity",  # Updraft helicity
    "zmla",  # Height of boundary layer
}

# Convective parameters (C2 only)
CONVECTIVE_PARAMETERS_C2 = {
    "CAPE",  # Convective available potential energy
    "CIN",  # Convective inhibition
    "MUEL",  # Equilibrium level height
    "FZL",  # Freezing level height
    "MLLCL",  # Lifting condensation level
    "LR03",  # 0-3 km lapse rate
    "LR75",  # 700-500 hPa lapse rate
}

# Fixed fields (available in fx frequency)
FIXED_VARIABLES = {
    "orog",  # Surface altitude
    "sftlf",  # Land-sea mask
}

# Default variables for renewable energy applications
# Includes essential solar/wind variables plus convective diagnostics for C2
DEFAULT_VARIABLES_R2_RE2 = [
    # Surface/2m variables
    "tas",
    "uas",
    "vas",
    "ps",
    "psl",
    "pr",
    "rsds",  # Direct shortwave (solar)
    "rsus",  # Reflected shortwave
    "rlds",  # Downwelling longwave
    # Pressure level variables
    "ta500",  # Temperature at 500 hPa
    "ua500",  # Wind at 500 hPa
    "va500",  # Wind at 500 hPa
    # Integrated variables
    "clt",  # Cloud cover affects solar
]

DEFAULT_VARIABLES_C2 = [
    # Surface/2m variables
    "tas",
    "uas",
    "vas",
    "ps",
    "pr",
    "rsds",  # Direct shortwave (solar)
    "rsus",  # Reflected shortwave
    "wsgs",  # Wind gust
    # Pressure level variables
    "ta500",
    "ua500",
    "va500",
    # Integrated variables
    "clt",
    # Convective parameters
    "CAPE",
    "MUEL",
]

# Mapping of model names to dataset info
MODEL_CONFIG = {
    "R2": {
        "label": "BARRA-R2",
        "description": "Moderate-scale deterministic reanalysis",
        "resolution": "11 km (0.11°)",
        "grid": "AUS-11",
        "domain": "Australia + surrounding (88.48-207.39°E, -57.97-12.98°N)",
        "temporal_res": ["1hr", "day", "mon"],
        "catalog_url": "https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/catalog.html",
        "opendap_url": "https://thredds.nci.org.au/thredds/dodsC/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1",
        "pressure_levels": [
            10,
            20,
            30,
            50,
            70,
            100,
            150,
            200,
            250,
            300,
            400,
            500,
            600,
            700,
            750,
            800,
            850,
            900,
            925,
            950,
            975,
            1000,
        ],
        "default_vars": DEFAULT_VARIABLES_R2_RE2,
    },
    "RE2": {
        "label": "BARRA-RE2",
        "description": "Moderate-scale ensemble reanalysis",
        "resolution": "22 km (0.22°)",
        "grid": "AUS-22",
        "domain": "Australia + surrounding (88.48-207.39°E, -57.97-12.98°N)",
        "temporal_res": ["1hr", "day", "mon"],
        "catalog_url": "https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUS-22/BOM/ERA5/historical/eda/BARRA-RE2/v1/1hr/catalog.html",
        "opendap_url": "https://thredds.nci.org.au/thredds/dodsC/ob53/output/reanalysis/AUS-22/BOM/ERA5/historical/eda/BARRA-RE2/v1",
        "pressure_levels": [
            10,
            20,
            30,
            50,
            70,
            100,
            150,
            200,
            250,
            300,
            400,
            500,
            600,
            700,
            750,
            800,
            850,
            900,
            925,
            950,
            975,
            1000,
        ],
        "default_vars": DEFAULT_VARIABLES_R2_RE2,
    },
    "C2": {
        "label": "BARRA-C2",
        "description": "Convective-scale reanalysis",
        "resolution": "4 km (0.04°)",
        "grid": "AUST-04",
        "domain": "Australia only (107.02-160.90°E, -46.69--4.01°N)",
        "temporal_res": ["1hr", "20min", "3hr", "day", "mon"],
        "catalog_url": "https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/1hr/catalog.html",
        "opendap_url": "https://thredds.nci.org.au/thredds/dodsC/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1",
        "pressure_levels": [
            10,
            20,
            30,
            50,
            70,
            100,
            150,
            200,
            250,
            300,
            400,
            500,
            600,
            700,
            750,
            800,
            850,
            900,
            925,
            950,
            975,
            1000,
        ],
        "default_vars": DEFAULT_VARIABLES_C2,
    },
}

# All available variables per resolution
ALL_VARIABLES_R2_RE2 = (
    SURFACE_VARIABLES_R2_RE2
    | PRESSURE_LEVEL_VARIABLES_R2_RE2
    | INTEGRATED_VARIABLES_R2_RE2
    | FIXED_VARIABLES
)

ALL_VARIABLES_C2 = (
    SURFACE_VARIABLES_C2
    | PRESSURE_LEVEL_VARIABLES_C2
    | INTEGRATED_VARIABLES_C2
    | CONVECTIVE_PARAMETERS_C2
    | FIXED_VARIABLES
)

# Pressure level suffixes for "ta", "ua", "va", "hus", "wap", "zg"
PRESSURE_LEVELS = [
    10,
    20,
    30,
    50,
    70,
    100,
    150,
    200,
    250,
    300,
    400,
    500,
    600,
    700,
    750,
    800,
    850,
    900,
    925,
    950,
    975,
    1000,
]
PRESSURE_LEVEL_VARS_BASE = ["ta", "ua", "va", "hus", "wap", "zg"]

# Map variable to its availability across resolutions
VARIABLE_AVAILABILITY = {
    # Common variables (all resolutions)
    "tas": {"R2", "RE2", "C2"},
    "uas": {"R2", "RE2", "C2"},
    "vas": {"R2", "RE2", "C2"},
    "ps": {"R2", "RE2", "C2"},
    "psl": {"R2", "RE2", "C2"},
    "pr": {"R2", "RE2", "C2"},
    "rsds": {"R2", "RE2", "C2"},
    # Pressure levels
    "ta": {"R2", "RE2", "C2"},
    "ua": {"R2", "RE2", "C2"},
    "va": {"R2", "RE2", "C2"},
    # C2 convective extras
    "CAPE": {"C2"},
    "CIN": {"C2"},
    "flashrate": {"C2"},
    "wsgs": {"C2"},
    "prga": {"C2"},
}
