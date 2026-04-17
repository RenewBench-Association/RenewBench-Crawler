"""ICON-DREAM variable mappings.

Constants for ICON-DREAM variables and metadata.
"""

# All available 3D model-level ICON-DREAM variables
ALL_MODEL_LEVEL_VARIABLES = {
    "T",
    "U",
    "V",
    "P",
    "QV",
    "TKE",
    "WS",
    "DEN",
}

# All available single-level (2D surface) ICON-DREAM variables
ALL_SINGLE_LEVEL_VARIABLES = {
    "T_2M",
    "U_10M",
    "V_10M",
    "TD_2M",
    "TOT_PREC",
    "PS",
    "PMSL",
    "CLCT",
    "ASWDIR_S",
    "ASWDIFD_S",
    "QV_S",
    "TMAX_2M",
    "TMIN_2M",
    "VMAX_10M",
    "WS_10M",
    "Z0",
}

# Default: 10 variables (6 single-level surface + 4 model-level atmospheric)
DEFAULT_VARIABLES = [
    # 2D surface variables
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "2m_temperature",
    "surface_pressure",
    "surface_solar_direct_radiation_downwards",
    "surface_solar_diffuse_radiation_downwards",
    "total_precipitation",
    # 3D model-level variables
    "temperature",
    "u_component_of_wind",
    "v_component_of_wind",
    "specific_humidity",
]

# Mapping of variable descriptions to DWD short codes
VARIABLE_TO_DWD_PARAM = {
    # Single-level variables
    "2m_temperature": "T_2M",
    "10m_u_component_of_wind": "U_10M",
    "10m_v_component_of_wind": "V_10M",
    "2m_dewpoint_temperature": "TD_2M",
    "total_precipitation": "TOT_PREC",
    "surface_pressure": "PS",
    "mean_sea_level_pressure": "PMSL",
    "total_cloud_cover": "CLCT",
    "surface_solar_direct_radiation_downwards": "ASWDIR_S",
    "surface_solar_diffuse_radiation_downwards": "ASWDIFD_S",
    "surface_specific_humidity": "QV_S",
    "2m_maximum_temperature": "TMAX_2M",
    "2m_minimum_temperature": "TMIN_2M",
    "10m_maximum_wind_speed": "VMAX_10M",
    "10m_wind_speed": "WS_10M",
    "surface_roughness_length": "Z0",
    # 3D model-level variables
    "temperature": "T",
    "u_component_of_wind": "U",
    "v_component_of_wind": "V",
    "pressure": "P",
    "specific_humidity": "QV",
    "turbulent_kinetic_energy": "TKE",
    "wind_speed": "WS",
    "density_moist_air": "DEN",
}

MODEL_CONFIG = {
    "global": {
        "label": "ICON-DREAM-Global",
        "dataset": "ICON-DREAM-Global (DWD Open Data)",
        "resolution": "~13km (icosahedral grid)",
        "base_url": "https://opendata.dwd.de/climate_environment/REA/ICON-DREAM-Global/hourly",
        "metadata_files": {
            "icon_grid_0026_R03B07_G.nc": (
                "http://icon-downloads.mpimet.mpg.de/grids/public/edzw/icon_grid_0026_R03B07_G.nc",
                "ICON-DREAM Global grid definition",
            ),
            "icon_grid_0026_R03B07_G-grfinfo.nc": (
                "http://icon-downloads.mpimet.mpg.de/grids/public/edzw/icon_grid_0026_R03B07_G-grfinfo.nc",
                "ICON-DREAM Global grid connectivity information",
            ),
        },
        "start_year": "2010",
    },
    "eu": {
        "label": "ICON-DREAM-EU",
        "dataset": "ICON-DREAM-EU (DWD Open Data)",
        "resolution": "~6.5km (icosahedral grid)",
        "base_url": "https://opendata.dwd.de/climate_environment/REA/ICON-DREAM-EU/hourly",
        "metadata_files": {
            "icon_grid_0027_R03B08_N02.nc": (
                "http://icon-downloads.mpimet.mpg.de/grids/public/edzw/icon_grid_0027_R03B08_N02.nc",
                "ICON-DREAM EU grid definition",
            ),
            "icon_grid_0027_R03B08_N02-grfinfo.nc": (
                "http://icon-downloads.mpimet.mpg.de/grids/public/edzw/icon_grid_0027_R03B08_N02-grfinfo.nc",
                "ICON-DREAM EU grid connectivity information",
            ),
        },
        "start_year": "2010",
    },
}
