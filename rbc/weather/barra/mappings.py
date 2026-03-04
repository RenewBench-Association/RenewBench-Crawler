"""BARRA2 variable mappings and metadata.

Constants for BARRA2 reanalysis variables and region configurations.

Model keys
----------
- R2:       BARRA2-R2 (11 km, 1 hr)
- C2:       BARRA2-C2 (4 km, 1 hr)
- C2_20min: BARRA2-C2 (4 km, 20 min)
"""

# All available single-level (2D surface) BARRA2 variables
ALL_SINGLE_LEVEL_VARIABLES = {
    "BWD03": {"C2"},  # Bulk wind difference (0–3 km)
    "BWD06": {"C2"},  # Bulk wind difference (0–6 km)
    "CAPE": {"R2", "C2"},  # Convective available potential energy
    "CIN": {"R2", "C2"},  # Convective inhibition
    "DCAPE": {"C2"},  # Downdraft CAPE
    "EBWD": {"C2"},  # Effective bulk wind difference
    "EILbase": {"C2"},  # Effective inflow layer base height
    "EILdepth": {"C2"},  # Effective inflow layer depth
    "ESRHl": {"C2"},  # Effective storm-relative helicity (left-moving)
    "ESRHr": {"C2"},  # Effective storm-relative helicity (right-moving)
    "FZL": {"C2"},  # Freezing level height
    "LR03": {"C2"},  # Lapse rate (0–3 km)
    "LR75": {"C2"},  # Lapse rate (700–500 hPa layer)
    "MLCAPE": {"C2"},  # Mixed-layer CAPE
    "MLCIN": {"C2"},  # Mixed-layer CIN
    "MLLCL": {"C2"},  # Mixed-layer lifting condensation level
    "MUCAPE": {"C2"},  # Most-unstable CAPE
    "MUCIN": {"C2"},  # Most-unstable CIN
    "MUEL": {"C2"},  # Most-unstable equilibrium level
    "MULPL": {"C2"},  # Most-unstable parcel level
    "MULPLmixr": {"C2"},  # Mixing ratio at most-unstable parcel level
    "MULPLpres": {"C2"},  # Pressure at most-unstable parcel level
    "MULPLtemp": {"C2"},  # Temperature at most-unstable parcel level
    "SRH01l": {"C2"},  # Storm-relative helicity 0–1 km (left-moving)
    "SRH01r": {"C2"},  # Storm-relative helicity 0–1 km (right-moving)
    "SRH03l": {"C2"},  # Storm-relative helicity 0–3 km (left-moving)
    "SRH03r": {"C2"},  # Storm-relative helicity 0–3 km (right-moving)
    "clh": {"R2", "C2"},  # High cloud fraction
    "clivi": {"R2", "C2"},  # Ice water path
    "cll": {"R2", "C2"},  # Low cloud fraction
    "clm": {"R2", "C2"},  # Mid-level cloud fraction
    "clt": {"R2", "C2"},  # Total cloud cover
    "clwvi": {"R2", "C2"},  # Condensed water path
    "coltotdrym": {"C2"},  # Column-integrated dry mass
    "coltotwetm": {"C2"},  # Column-integrated wet mass
    "evspsbl": {"R2", "C2"},  # Evaporation
    "evspsblpot": {"R2", "C2"},  # Potential evaporation
    "flashrate": {"C2"},  # Lightning flash rate
    "fogfraction": {"C2"},  # Fog fraction
    "helicitymax": {"C2"},  # Maximum updraft helicity
    "helicitymin": {"C2"},  # Minimum updraft helicity
    "hfls": {"R2", "C2"},  # Surface latent heat flux
    "hfss": {"R2", "C2"},  # Surface sensible heat flux
    "hurs": {"R2", "C2"},  # Near-surface relative humidity
    "huss": {"R2", "C2"},  # Near-surface specific humidity
    "maxcolrefl": {"C2"},  # Maximum column radar reflectivity
    "maxcolwa": {"C2"},  # Maximum column vertical velocity
    "mrfsos": {"R2", "C2"},  # Surface soil moisture flux
    "mrro": {"C2"},  # Total runoff
    "mrros": {"C2"},  # Surface runoff
    "mrsos": {"R2", "C2"},  # Moisture in upper soil layer
    "pr": {"R2", "C2"},  # Total precipitation
    "prc": {"R2"},  # Convective precipitation
    "prga": {"C2"},  # Graupel sedimentation rate
    "prmax": {"R2", "C2"},  # Maximum hourly precipitation
    "prra": {"C2"},  # Large-scale rainfall rate
    "prsn": {"R2", "C2", "C2_20min"},  # Snowfall flux
    "prsnmax": {"C2"},  # Maximum hourly snowfall
    "prw": {"R2", "C2"},  # Precipitable water
    "ps": {"R2", "C2"},  # Surface pressure
    "psl": {"R2", "C2", "C2_20min"},  # Mean sea level pressure
    "radrefl1km": {"C2_20min"},  # Radar reflectivity at 1 km
    "rlds": {"R2", "C2"},  # Surface downwelling longwave radiation
    "rldscs": {"R2", "C2"},  # Surface downwelling longwave radiation (clear-sky)
    "rlus": {"R2", "C2"},  # Surface upwelling longwave radiation
    "rluscs": {"R2", "C2"},  # Surface upwelling longwave radiation (clear-sky)
    "rlut": {"R2", "C2"},  # TOA outgoing longwave radiation
    "rlutcs": {"R2", "C2"},  # TOA outgoing longwave radiation (clear-sky)
    "rsds": {"R2", "C2"},  # Surface downwelling shortwave radiation
    "rsdscs": {"R2", "C2"},  # Surface downwelling shortwave radiation (clear-sky)
    "rsdsdif": {"C2_20min"},  # Surface diffuse downwelling shortwave radiation
    "rsdsdir": {
        "R2",
        "C2",
        "C2_20min",
    },  # Surface direct downwelling shortwave radiation
    "rsdt": {"R2", "C2"},  # TOA incoming shortwave radiation
    "rss": {"C2_20min"},  # Surface net shortwave radiation
    "rsus": {"R2", "C2"},  # Surface upwelling shortwave radiation
    "rsuscs": {"R2", "C2"},  # Surface upwelling shortwave radiation (clear-sky)
    "rsut": {"R2", "C2"},  # TOA outgoing shortwave radiation
    "rsutcs": {"R2", "C2"},  # TOA outgoing shortwave radiation (clear-sky)
    "sfcWind": {"R2", "C2"},  # Near-surface wind speed
    "sfcWindmax": {"R2", "C2"},  # Maximum near-surface wind speed
    "ta100m": {"R2", "C2", "C2_20min"},  # Air temperature at 100 m
    "ta1500m": {"R2", "C2", "C2_20min"},  # Air temperature at 1500 m
    "ta150m": {"R2", "C2", "C2_20min"},  # Air temperature at 150 m
    "ta200m": {"R2", "C2", "C2_20min"},  # Air temperature at 200 m
    "ta250m": {"R2", "C2", "C2_20min"},  # Air temperature at 250 m
    "ta50m": {"R2", "C2", "C2_20min"},  # Air temperature at 50 m
    "tas": {"R2", "C2", "C2_20min"},  # 1.5 m air temperature
    "tasmax": {"R2", "C2"},  # Maximum 1.5 m air temperature
    "tasmean": {"R2", "C2"},  # Mean 1.5 m air temperature
    "tasmin": {"R2", "C2"},  # Minimum 1.5 m air temperature
    "ts": {"R2", "C2", "C2_20min"},  # Surface temperature
    "tsmean": {"C2"},  # Mean surface temperature
    "twiso": {"R2", "C2"},  # Isobaric wet-bulb temperature
    "twpse": {"R2", "C2"},  # Pseudo wet-bulb temperature
    "ua100m": {"R2", "C2", "C2_20min"},  # Eastward wind at 100 m
    "ua1500m": {"R2", "C2", "C2_20min"},  # Eastward wind at 1500 m
    "ua150m": {"R2", "C2", "C2_20min"},  # Eastward wind at 150 m
    "ua200m": {"R2", "C2", "C2_20min"},  # Eastward wind at 200 m
    "ua250m": {"R2", "C2", "C2_20min"},  # Eastward wind at 250 m
    "ua50m": {"R2", "C2", "C2_20min"},  # Eastward wind at 50 m
    "uas": {"R2", "C2", "C2_20min"},  # 10 m eastward wind
    "uasmax": {"R2"},  # Maximum 10 m eastward wind
    "uasmean": {"R2", "C2"},  # Mean 10 m eastward wind
    "va100m": {"R2", "C2", "C2_20min"},  # Northward wind at 100 m
    "va1500m": {"R2", "C2", "C2_20min"},  # Northward wind at 1500 m
    "va150m": {"R2", "C2", "C2_20min"},  # Northward wind at 150 m
    "va200m": {"R2", "C2", "C2_20min"},  # Northward wind at 200 m
    "va250m": {"R2", "C2", "C2_20min"},  # Northward wind at 250 m
    "va50m": {"R2", "C2", "C2_20min"},  # Northward wind at 50 m
    "vas": {"R2", "C2", "C2_20min"},  # 10 m northward wind
    "vasmax": {"R2"},  # Maximum 10 m northward wind
    "vasmean": {"R2", "C2"},  # Mean 10 m northward wind
    "visibility": {"C2"},  # Horizontal visibility
    "wsgs": {"C2"},  # Wind gust speed
    "wsgsmax": {"R2", "C2", "C2_20min"},  # Maximum wind gust speed
    "zmla": {"R2", "C2"},  # Boundary-layer height
    "ztp": {"C2"},  # Tropopause height
    "omega500": {"R2"},  # Vertical velocity at 500 hPa
}

R2_SINGLE_LEVEL_VARIABLES = {
    v for v, m in ALL_SINGLE_LEVEL_VARIABLES.items() if "R2" in m
}
C2_SINGLE_LEVEL_VARIABLES = {
    v for v, m in ALL_SINGLE_LEVEL_VARIABLES.items() if "C2" in m
}
C2_20MIN_SINGLE_LEVEL_VARIABLES = {
    v for v, m in ALL_SINGLE_LEVEL_VARIABLES.items() if "C2_20min" in m
}


# All available 3D pressure-level BARRA2 variables
ALL_PRESSURE_LEVEL_VARIABLES = {
    "ta": {"R2", "C2"},  # Air temperature (pressure levels)
    "ua": {"R2", "C2"},  # Eastward wind (pressure levels)
    "va": {"R2", "C2"},  # Northward wind (pressure levels)
    "hus": {"R2", "C2"},  # Specific humidity (pressure levels)
    "wa": {"R2", "C2"},  # Vertical velocity (pressure levels)
    "zg": {"R2", "C2"},  # Geopotential height (pressure levels)
    "wap": {"C2"},  # Vertical velocity in pressure coordinates (C2 only)
}

R2_PRESSURE_LEVEL_VARIABLES = {
    v for v, m in ALL_PRESSURE_LEVEL_VARIABLES.items() if "R2" in m
}
C2_PRESSURE_LEVEL_VARIABLES = {
    v for v, m in ALL_PRESSURE_LEVEL_VARIABLES.items() if "C2" in m
}

# Invariant (time-independent) fields
INVARIANT_VARIABLES = {
    "orog",  # Surface altitude
    "sftlf",  # Land-sea mask
}

# Default: 13 variables (8 single-level surface + 5 pressure-level atmospheric)
DEFAULT_VARIABLES = [
    # 2D surface variables
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "100m_u_component_of_wind",
    "100m_v_component_of_wind",
    "1.5m_temperature",
    "surface_pressure",
    "surface_solar_radiation_downwards",
    "total_precipitation",
    # 3D pressure level variables
    "temperature",
    "u_component_of_wind",
    "v_component_of_wind",
    "specific_humidity",
    "geopotential_height",
]

# Pressure levels
ALL_PRESSURE_LEVELS = {
    200: {"R2", "C2"},
    300: {"R2", "C2"},
    400: {"R2", "C2"},
    500: {"R2", "C2"},
    600: {"R2", "C2"},
    700: {"R2", "C2"},
    750: {"C2"},
    800: {"C2"},
    850: {"R2", "C2"},
    900: {"C2"},
    925: {"R2", "C2"},
    950: {"R2", "C2"},
    975: {"C2"},
    1000: {"R2", "C2"},
}

R2_PRESSURE_LEVELS = sorted(
    level for level, models in ALL_PRESSURE_LEVELS.items() if "R2" in models
)

C2_PRESSURE_LEVELS = sorted(
    level for level, models in ALL_PRESSURE_LEVELS.items() if "C2" in models
)

# Default: 1000, 950 hPa (lowest 2 pressure levels, ~110m, ~560m altitude)
R2_DEFAULT_PRESSURE_LEVELS = ["1000", "950"]

# Default: 1000, 975, 950 hPa (lowest 3 pressure levels, ~110m, ~300m, ~560m altitude)
C2_DEFAULT_PRESSURE_LEVELS = ["1000", "975", "950"]

# Model configs and mapping of model names to dataset info
MODEL_CONFIG = {
    "R2": {
        "label": "BARRA-R2",
        "description": "Moderate-scale deterministic reanalysis",
        "resolution": "11 km (0.11°)",
        "grid": "AUS-11",
        "domain": "Australia + surrounding (88.48-207.39°E, -57.97-12.98°N)",
        "temporal_res": "1hr",
        "catalog_url": "https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/catalog.html",
        "invariant_catalog_url": "https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/fx/catalog.html",
        "opendap_url": "https://thredds.nci.org.au/thredds/dodsC/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1",
        "invariant_path": "fx",
    },
    "C2": {
        "label": "BARRA-C2",
        "description": "Convective-scale reanalysis (1hr)",
        "resolution": "4 km (0.04°)",
        "grid": "AUST-04",
        "domain": "Australia only (107.02-160.90°E, -46.69--4.01°N)",
        "temporal_res": "1hr",
        "catalog_url": "https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/1hr/catalog.html",
        "invariant_catalog_url": "https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/fx/catalog.html",
        "opendap_url": "https://thredds.nci.org.au/thredds/dodsC/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1",
        "invariant_path": "fx",
    },
    "C2_20min": {
        "label": "BARRA-C2",
        "description": "Convective-scale reanalysis (20min)",
        "resolution": "4 km (0.04°)",
        "grid": "AUST-04",
        "domain": "Australia only (107.02-160.90°E, -46.69--4.01°N)",
        "temporal_res": "20min",
        "catalog_url": "https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/20min/catalog.html",
        "invariant_catalog_url": "https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/fx/catalog.html",
        "opendap_url": "https://thredds.nci.org.au/thredds/dodsC/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1",
        "invariant_path": "fx",
    },
}

# Mapping of variable descriptions to BARRA short codes
VARIABLE_TO_BARRA_PARAM = {
    # Temperature
    "1.5m_temperature": "tas",
    "1.5m_temperature_mean": "tasmean",
    "1.5m_maximum_temperature": "tasmax",
    "1.5m_minimum_temperature": "tasmin",
    "surface_temperature": "ts",
    "surface_temperature_mean": "tsmean",
    "50m_temperature": "ta50m",
    "100m_temperature": "ta100m",
    "150m_temperature": "ta150m",
    "200m_temperature": "ta200m",
    "250m_temperature": "ta250m",
    "1500m_temperature": "ta1500m",
    # Wind
    "10m_u_component_of_wind": "uas",
    "10m_u_component_of_wind_mean": "uasmean",
    "10m_u_component_of_wind_maximum": "uasmax",
    "50m_u_component_of_wind": "ua50m",
    "100m_u_component_of_wind": "ua100m",
    "150m_u_component_of_wind": "ua150m",
    "200m_u_component_of_wind": "ua200m",
    "250m_u_component_of_wind": "ua250m",
    "1500m_u_component_of_wind": "ua1500m",
    "10m_v_component_of_wind": "vas",
    "10m_v_component_of_wind_mean": "vasmean",
    "10m_v_component_of_wind_maximum": "vasmax",
    "50m_v_component_of_wind": "va50m",
    "100m_v_component_of_wind": "va100m",
    "150m_v_component_of_wind": "va150m",
    "200m_v_component_of_wind": "va200m",
    "250m_v_component_of_wind": "va250m",
    "1500m_v_component_of_wind": "va1500m",
    "10m_wind_speed": "sfcWind",
    "10m_maximum_wind_speed": "sfcWindmax",
    "wind_gust_speed": "wsgs",
    "maximum_wind_gust_speed": "wsgsmax",
    # Pressure / moisture / precipitation
    "surface_pressure": "ps",
    "mean_sea_level_pressure": "psl",
    "total_precipitation": "pr",
    "convective_precipitation": "prc",
    "graupel_sediment_rate": "prga",
    "large_scale_rainfall_rate": "prra",
    "maximum_hourly_precipitation": "prmax",
    "snowfall": "prsn",
    "maximum_hourly_snowfall": "prsnmax",
    "precipitable_water": "prw",
    "1.5m_relative_humidity": "hurs",
    "1.5m_specific_humidity": "huss",
    # Radiation / fluxes
    "surface_solar_radiation_downwards": "rsds",
    "surface_solar_radiation_upwards": "rsus",
    "surface_solar_radiation_downwards_clear_sky": "rsdscs",
    "surface_solar_radiation_upwards_clear_sky": "rsuscs",
    "surface_direct_solar_radiation_downwards": "rsdsdir",
    "surface_diffuse_solar_radiation_downwards": "rsdsdif",
    "surface_net_shortwave_radiation": "rss",
    "toa_incoming_shortwave_radiation": "rsdt",
    "toa_outgoing_shortwave_radiation": "rsut",
    "toa_outgoing_shortwave_radiation_clear_sky": "rsutcs",
    "surface_thermal_radiation_downwards": "rlds",
    "surface_thermal_radiation_upwards": "rlus",
    "surface_thermal_radiation_downwards_clear_sky": "rldscs",
    "surface_thermal_radiation_upwards_clear_sky": "rluscs",
    "toa_outgoing_longwave_radiation": "rlut",
    "toa_outgoing_longwave_radiation_clear_sky": "rlutcs",
    "surface_latent_heat_flux": "hfls",
    "surface_sensible_heat_flux": "hfss",
    "evaporation": "evspsbl",
    "potential_evaporation": "evspsblpot",
    # Cloud / column / hydrology
    "total_cloud_cover": "clt",
    "high_cloud_cover": "clh",
    "medium_cloud_cover": "clm",
    "low_cloud_cover": "cll",
    "condensed_water_path": "clwvi",
    "ice_water_path": "clivi",
    "surface_soil_moisture_flux": "mrfsos",
    "upper_soil_layer_moisture": "mrsos",
    "total_runoff": "mrro",
    "surface_runoff": "mrros",
    "column_total_dry_mass": "coltotdrym",
    "column_total_wet_mass": "coltotwetm",
    # Storm diagnostics
    "lightning_flash_rate": "flashrate",
    "fog_fraction": "fogfraction",
    "visibility": "visibility",
    "maximum_column_reflectivity": "maxcolrefl",
    "maximum_column_vertical_velocity": "maxcolwa",
    "radar_reflectivity_at_1km": "radrefl1km",
    "updraft_helicity_maximum": "helicitymax",
    "updraft_helicity_minimum": "helicitymin",
    "boundary_layer_height": "zmla",
    "tropopause_height": "ztp",
    "convective_available_potential_energy": "CAPE",
    "convective_inhibition": "CIN",
    "downdraft_cape": "DCAPE",
    "effective_bulk_wind_difference": "EBWD",
    "bulk_wind_difference_0_3km": "BWD03",
    "bulk_wind_difference_0_6km": "BWD06",
    "effective_inflow_layer_base": "EILbase",
    "effective_inflow_layer_depth": "EILdepth",
    "storm_relative_helicity_0_1km_left": "SRH01l",
    "storm_relative_helicity_0_1km_right": "SRH01r",
    "storm_relative_helicity_0_3km_left": "SRH03l",
    "storm_relative_helicity_0_3km_right": "SRH03r",
    "effective_storm_relative_helicity_left": "ESRHl",
    "effective_storm_relative_helicity_right": "ESRHr",
    "mixed_layer_cape": "MLCAPE",
    "mixed_layer_cin": "MLCIN",
    "most_unstable_cape": "MUCAPE",
    "most_unstable_cin": "MUCIN",
    "equilibrium_level_height": "MUEL",
    "most_unstable_lifting_parcel_level": "MULPL",
    "most_unstable_lifting_parcel_temperature": "MULPLtemp",
    "most_unstable_lifting_parcel_pressure": "MULPLpres",
    "most_unstable_lifting_parcel_mixing_ratio": "MULPLmixr",
    "lifting_condensation_level": "MLLCL",
    "freezing_level_height": "FZL",
    "lapse_rate_0_3km": "LR03",
    "lapse_rate_700_500hPa": "LR75",
    "isobaric_wet_bulb_temperature": "twiso",
    "pseudo_wet_bulb_temperature": "twpse",
    "vertical_velocity_500hpa": "omega500",
    # 3D variable families
    "temperature": "ta",
    "u_component_of_wind": "ua",
    "v_component_of_wind": "va",
    "specific_humidity": "hus",
    "vertical_velocity": "wa",
    "geopotential_height": "zg",
    "vertical_velocity_in_pressure": "wap",
    # Invariant fields
    "orography": "orog",
    "land_sea_mask": "sftlf",
}
