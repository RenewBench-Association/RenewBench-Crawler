"""ERA5 variable and level mappings.

Constants for ERA5 variables, pressure levels, model levels, and CDS / MARS parameter codes.
"""

from typing import TypedDict

# Surface and single-level variables
ALL_SINGLE_LEVEL_VARIABLES = {
    # Surface and single level parameters: instantaneous
    "convective_inhibition",  # Convective inhibition, J kg**-1
    "friction_velocity",  # Friction velocity, m s**-1
    "lake_mix_layer_temperature",  # Lake mix-layer temperature, K
    "lake_mix_layer_depth",  # Lake mix-layer depth, m
    "lake_bottom_temperature",  # Lake bottom temperature, K
    "lake_total_layer_temperature",  # Lake total layer temperature, K
    "lake_shape_factor",  # Lake shape factor, dimensionless
    "lake_ice_temperature",  # Lake ice temperature, K
    "lake_ice_depth",  # Lake ice depth, m
    "uv_visible_albedo_for_direct_radiation",  # UV visible albedo for direct radiation, (0 - 1)
    "minimum_vertical_gradient_of_refractivity_inside_trapping_layer",  # Minimum vertical gradient of refractivity inside trapping layer, m**-1
    "uv_visible_albedo_for_diffuse_radiation",  # UV visible albedo for diffuse radiation, (0 - 1)
    "mean_vertical_gradient_of_refractivity_inside_trapping_layer",  # Mean vertical gradient of refractivity inside trapping layer, m**-1
    "near_ir_albedo_for_direct_radiation",  # Near IR albedo for direct radiation, (0 - 1)
    "duct_base_height",  # Duct base height, m
    "near_ir_albedo_for_diffuse_radiation",  # Near IR albedo for diffuse radiation, (0 - 1)
    "trapping_layer_base_height",  # Trapping layer base height, m
    "trapping_layer_top_height",  # Trapping layer top height, m
    "cloud_base_height",  # Cloud base height, m
    "zero_degree_level",  # Zero degree level, m
    "instantaneous_10m_wind_gust",  # Instantaneous 10 metre wind gust, m s**-1
    "sea_ice_cover",  # Sea ice area fraction, (0 - 1)
    "snow_albedo",  # Snow albedo, (0 - 1)
    "snow_density",  # Snow density, kg m**-3
    "sea_surface_temperature",  # Sea surface temperature, K
    "ice_temperature_layer_1",  # Ice temperature layer 1, K
    "ice_temperature_layer_2",  # Ice temperature layer 2, K
    "ice_temperature_layer_3",  # Ice temperature layer 3, K
    "ice_temperature_layer_4",  # Ice temperature layer 4, K
    "volumetric_soil_water_layer_1",  # Volumetric soil water layer 1 1, m**3 m**-3
    "volumetric_soil_water_layer_2",  # Volumetric soil water layer 2 1, m**3 m**-3
    "volumetric_soil_water_layer_3",  # Volumetric soil water layer 3 1, m**3 m**-3
    "volumetric_soil_water_layer_4",  # Volumetric soil water layer 4 1, m**3 m**-3
    "convective_available_potential_energy",  # Convective available potential energy, J kg**-1
    "leaf_area_index_low_vegetation",  # Leaf area index, low vegetation 3, m**2 m**-2
    "leaf_area_index_high_vegetation",  # Leaf area index, high vegetation 3, m**2 m**-2
    "10m_u_component_of_neutral_wind",  # Neutral wind at 10 m u-component, m s**-1
    "10m_v_component_of_neutral_wind",  # Neutral wind at 10 m v-component, m s**-1
    "surface_pressure",  # Surface pressure, Pa
    "soil_temperature_level_1",  # Soil temperature level 1 1, K
    "snow_depth",  # Snow depth, m of water equivalent
    "charnock",  # Charnock, ~
    "mean_sea_level_pressure",  # Mean sea level pressure, Pa
    "boundary_layer_height",  # Boundary layer height, m
    "total_cloud_cover",  # Total cloud cover, (0 - 1)
    "10m_u_component_of_wind",  # 10 metre U wind component, m s**-1
    "10m_v_component_of_wind",  # 10 metre V wind component, m s**-1
    "2m_temperature",  # 2 metre temperature, K
    "2m_dewpoint_temperature",  # 2 metre dewpoint temperature, K
    "soil_temperature_level_2",  # Soil temperature level 2 1, K
    "soil_temperature_level_3",  # Soil temperature level 3 1, K
    "low_cloud_cover",  # Low cloud cover, (0 - 1)
    "medium_cloud_cover",  # Medium cloud cover, (0 - 1)
    "high_cloud_cover",  # High cloud cover, (0 - 1)
    "skin_reservoir_content",  # Skin reservoir content, m of water equivalent
    "instantaneous_large_scale_surface_precipitation_fraction",  # Instantaneous large-scale surface precipitation fraction, (0 - 1)
    "convective_rain_rate",  # Convective rain rate, kg m**-2 s**-1
    "large_scale_rain_rate",  # Large scale rain rate, kg m**-2 s**-1
    "convective_snowfall_rate_water_equivalent",  # Convective snowfall rate water equivalent, kg m**-2 s**-1
    "large_scale_snowfall_rate_water_equivalent",  # Large scale snowfall rate water equivalent, kg m**-2 s**-1
    "instantaneous_eastward_turbulent_surface_stress",  # Instantaneous eastward turbulent surface stress, N m**-2
    "instantaneous_northward_turbulent_surface_stress",  # Instantaneous northward turbulent surface stress, N m**-2
    "instantaneous_surface_sensible_heat_flux",  # Instantaneous surface sensible heat flux, W m**-2
    "instantaneous_moisture_flux",  # Instantaneous moisture flux, kg m**-2 s**-1
    "skin_temperature",  # Skin temperature, K
    "soil_temperature_level_4",  # Soil temperature level 4 1, K
    "temperature_of_snow_layer",  # Temperature of snow layer, K
    "forecast_albedo",  # Forecast albedo, (0 - 1)
    "forecast_surface_roughness",  # Forecast surface roughness, m
    "forecast_logarithm_of_surface_roughness_for_heat",  # Forecast logarithm of surface roughness for heat, ~
    "100m_u_component_of_wind",  # 100 metre U wind component, m s**-1
    "100m_v_component_of_wind",  # 100 metre V wind component, m s**-1
    "precipitation_type",  # Precipitation type 2, code table (4.201)
    "k_index",  # K index 2, K
    "total_totals_index",  # Total totals index 2, K
    # Surface and single level parameters: accumulated
    "large_scale_precipitation_fraction",  # Large-scale precipitation fraction, s
    "downward_uv_radiation_at_the_surface",  # Downward UV radiation at the surface, J m**-2
    "boundary_layer_dissipation",  # Boundary layer dissipation, J m**-2
    "surface_sensible_heat_flux",  # Surface sensible heat flux, J m**-2
    "surface_latent_heat_flux",  # Surface latent heat flux, J m**-2
    "surface_solar_radiation_downwards",  # Surface solar radiation downwards, J m**-2
    "surface_thermal_radiation_downwards",  # Surface thermal radiation downwards, J m**-2
    "surface_net_solar_radiation",  # Surface net solar radiation, J m**-2
    "surface_net_thermal_radiation",  # Surface net thermal radiation, J m**-2
    "top_net_solar_radiation",  # Top net solar radiation, J m**-2
    "top_net_thermal_radiation",  # Top net thermal radiation, J m**-2
    "eastward_turbulent_surface_stress",  # Eastward turbulent surface stress, N m**-2 s
    "northward_turbulent_surface_stress",  # Northward turbulent surface stress, N m**-2 s
    "eastward_gravity_wave_surface_stress",  # Eastward gravity wave surface stress, N m**-2 s
    "northward_gravity_wave_surface_stress",  # Northward gravity wave surface stress, N m**-2 s
    "gravity_wave_dissipation",  # Gravity wave dissipation, J m**-2
    "top_net_solar_radiation_clear_sky",  # Top net solar radiation, clear sky, J m**-2
    "top_net_thermal_radiation_clear_sky",  # Top net thermal radiation, clear sky, J m**-2
    "surface_net_solar_radiation_clear_sky",  # Surface net solar radiation, clear sky, J m**-2
    "surface_net_thermal_radiation_clear_sky",  # Surface net thermal radiation, clear sky, J m**-2
    "toa_incident_solar_radiation",  # TOA incident solar radiation, J m**-2
    "vertically_integrated_moisture_divergence",  # Vertically integrated moisture divergence, kg m**-2
    "total_sky_direct_solar_radiation_at_surface",  # Total sky direct solar radiation at surface, J m**-2
    "clear_sky_direct_solar_radiation_at_surface",  # Clear-sky direct solar radiation at surface, J m**-2
    "surface_solar_radiation_downward_clear_sky",  # Surface solar radiation downward clear-sky, J m**-2
    "surface_thermal_radiation_downward_clear_sky",  # Surface thermal radiation downward clear-sky, J m**-2
    "surface_runoff",  # Surface runoff, m
    "sub_surface_runoff",  # Sub-surface runoff, m
    "snow_evaporation",  # Snow evaporation, m of water equivalent
    "snowmelt",  # Snowmelt, m of water equivalent
    "large_scale_precipitation",  # Large-scale precipitation, m
    "convective_precipitation",  # Convective precipitation, m
    "snowfall",  # Snowfall, m of water equivalent
    "evaporation",  # Evaporation, m of water equivalent
    "runoff",  # Runoff, m
    "total_precipitation",  # Total precipitation, m
    "convective_snowfall",  # Convective snowfall, m of water equivalent
    "large_scale_snowfall",  # Large-scale snowfall, m of water equivalent
    "potential_evaporation",  # Potential evaporation, m
    # Surface and single level parameters: mean rates/fluxes
    "mean_surface_runoff_rate",  # Mean surface runoff rate, kg m**-2 s**-1
    "mean_sub_surface_runoff_rate",  # Mean sub-surface runoff rate, kg m**-2 s**-1
    "mean_snow_evaporation_rate",  # Mean snow evaporation rate, kg m**-2 s**-1
    "mean_snowmelt_rate",  # Mean snowmelt rate, kg m**-2 s**-1
    "mean_large_scale_precipitation_fraction",  # Mean large-scale precipitation fraction, Proportion
    "mean_surface_downward_uv_radiation_flux",  # Mean surface downward UV radiation flux, W m**-2
    "mean_large_scale_precipitation_rate",  # Mean large-scale precipitation rate, kg m**-2 s**-1
    "mean_convective_precipitation_rate",  # Mean convective precipitation rate, kg m**-2 s**-1
    "mean_snowfall_rate",  # Mean snowfall rate, kg m**-2 s**-1
    "mean_boundary_layer_dissipation",  # Mean boundary layer dissipation, W m**-2
    "mean_surface_sensible_heat_flux",  # Mean surface sensible heat flux, W m**-2
    "mean_surface_latent_heat_flux",  # Mean surface latent heat flux, W m**-2
    "mean_surface_downward_short_wave_radiation_flux",  # Mean surface downward short-wave radiation flux, W m**-2
    "mean_surface_downward_long_wave_radiation_flux",  # Mean surface downward long-wave radiation flux, W m**-2
    "mean_surface_net_short_wave_radiation_flux",  # Mean surface net short-wave radiation flux, W m**-2
    "mean_surface_net_long_wave_radiation_flux",  # Mean surface net long-wave radiation flux, W m**-2
    "mean_top_net_short_wave_radiation_flux",  # Mean top net short-wave radiation flux, W m**-2
    "mean_top_net_long_wave_radiation_flux",  # Mean top net long-wave radiation flux, W m**-2
    "mean_eastward_turbulent_surface_stress",  # Mean eastward turbulent surface stress, N m**-2
    "mean_northward_turbulent_surface_stress",  # Mean northward turbulent surface stress, N m**-2
    "mean_evaporation_rate",  # Mean evaporation rate, kg m**-2 s**-1
    "mean_eastward_gravity_wave_surface_stress",  # Mean eastward gravity wave surface stress, N m**-2
    "mean_northward_gravity_wave_surface_stress",  # Mean northward gravity wave surface stress, N m**-2
    "mean_gravity_wave_dissipation",  # Mean gravity wave dissipation, W m**-2
    "mean_runoff_rate",  # Mean runoff rate, kg m**-2 s**-1
    "mean_top_net_short_wave_radiation_flux_clear_sky",  # Mean top net short-wave radiation flux, clear sky, W m**-2
    "mean_top_net_long_wave_radiation_flux_clear_sky",  # Mean top net long-wave radiation flux, clear sky, W m**-2
    "mean_surface_net_short_wave_radiation_flux_clear_sky",  # Mean surface net short-wave radiation flux, clear sky, W m**-2
    "mean_surface_net_long_wave_radiation_flux_clear_sky",  # Mean surface net long-wave radiation flux, clear sky, W m**-2
    "mean_top_downward_short_wave_radiation_flux",  # Mean top downward short-wave radiation flux, W m**-2
    "mean_vertically_integrated_moisture_divergence",  # Mean vertically integrated moisture divergence, kg m**-2 s**-1
    "mean_total_precipitation_rate",  # Mean total precipitation rate, kg m**-2 s**-1
    "mean_convective_snowfall_rate",  # Mean convective snowfall rate, kg m**-2 s**-1
    "mean_large_scale_snowfall_rate",  # Mean large-scale snowfall rate, kg m**-2 s**-1
    "mean_surface_direct_short_wave_radiation_flux",  # Mean surface direct short-wave radiation flux, W m**-2
    "mean_surface_direct_short_wave_radiation_flux_clear_sky",  # Mean surface direct short-wave radiation flux, clear sky, W m**-2
    "mean_surface_downward_short_wave_radiation_flux_clear_sky",  # Mean surface downward short-wave radiation flux, clear sky, W m**-2
    "mean_surface_downward_long_wave_radiation_flux_clear_sky",  # Mean surface downward long-wave radiation flux, clear sky, W m**-2
    "mean_potential_evaporation_rate",  # Mean potential evaporation rate, kg m**-2 s**-1
    # Surface and single level parameters: minimum/maximum
    "10m_wind_gust_since_previous_post_processing",  # 10 metre wind gust since previous post-processing, m s**-1
    "maximum_2m_temperature_since_previous_post_processing",  # Maximum temperature at 2 metres since previous post-processing, K
    "minimum_2m_temperature_since_previous_post_processing",  # Minimum temperature at 2 metres since previous post-processing, K
    "maximum_total_precipitation_rate_since_previous_post_processing",  # Maximum total precipitation rate since previous post-processing, kg m**-2 s**-1
    "minimum_total_precipitation_rate_since_previous_post_processing",  # Minimum total precipitation rate since previous post-processing, kg m**-2 s**-1
    # Surface and single level parameters: vertical integrals and total column: instantaneous
    "vertical_integral_of_mass_of_atmosphere",  # Vertical integral of mass of atmosphere, kg m**-2
    "vertical_integral_of_temperature",  # Vertical integral of temperature, K kg m**-2
    "vertical_integral_of_kinetic_energy",  # Vertical integral of kinetic energy, J m**-2
    "vertical_integral_of_thermal_energy",  # Vertical integral of thermal energy, J m**-2
    "vertical_integral_of_potential_and_internal_energy",  # Vertical integral of potential+internal energy, J m**-2
    "vertical_integral_of_potential_internal_and_latent_energy",  # Vertical integral of potential+internal+latent energy, J m**-2
    "vertical_integral_of_total_energy",  # Vertical integral of total energy, J m**-2
    "vertical_integral_of_energy_conversion",  # Vertical integral of energy conversion, W m**-2
    "vertical_integral_of_eastward_mass_flux",  # Vertical integral of eastward mass flux, kg m**-1 s**-1
    "vertical_integral_of_northward_mass_flux",  # Vertical integral of northward mass flux, kg m**-1 s**-1
    "vertical_integral_of_eastward_kinetic_energy_flux",  # Vertical integral of eastward kinetic energy flux, W m**-1
    "vertical_integral_of_northward_kinetic_energy_flux",  # Vertical integral of northward kinetic energy flux, W m**-1
    "vertical_integral_of_eastward_heat_flux",  # Vertical integral of eastward heat flux, W m**-1
    "vertical_integral_of_northward_heat_flux",  # Vertical integral of northward heat flux, W m**-1
    "vertical_integral_of_eastward_water_vapour_flux",  # Vertical integral of eastward water vapour flux, kg m**-1 s**-1
    "vertical_integral_of_northward_water_vapour_flux",  # Vertical integral of northward water vapour flux, kg m**-1 s**-1
    "vertical_integral_of_eastward_geopotential_flux",  # Vertical integral of eastward geopotential flux, W m**-1
    "vertical_integral_of_northward_geopotential_flux",  # Vertical integral of northward geopotential flux, W m**-1
    "vertical_integral_of_eastward_total_energy_flux",  # Vertical integral of eastward total energy flux, W m**-1
    "vertical_integral_of_northward_total_energy_flux",  # Vertical integral of northward total energy flux, W m**-1
    "vertical_integral_of_eastward_ozone_flux",  # Vertical integral of eastward ozone flux, kg m**-1 s**-1
    "vertical_integral_of_northward_ozone_flux",  # Vertical integral of northward ozone flux, kg m**-1 s**-1
    "vertical_integral_of_divergence_of_cloud_liquid_water_flux",  # Vertical integral of divergence of cloud liquid water flux, kg m**-2 s**-1
    "vertical_integral_of_divergence_of_cloud_frozen_water_flux",  # Vertical integral of divergence of cloud frozen water flux, kg m**-2 s**-1
    "vertical_integral_of_divergence_of_mass_flux",  # Vertical integral of divergence of mass flux, kg m**-2 s**-1
    "vertical_integral_of_divergence_of_kinetic_energy_flux",  # Vertical integral of divergence of kinetic energy flux, W m**-2
    "vertical_integral_of_divergence_of_thermal_energy_flux",  # Vertical integral of divergence of thermal energy flux, W m**-2
    "vertical_integral_of_divergence_of_moisture_flux",  # Vertical integral of divergence of moisture flux, kg m**-2 s**-1
    "vertical_integral_of_divergence_of_geopotential_flux",  # Vertical integral of divergence of geopotential flux, W m**-2
    "vertical_integral_of_divergence_of_total_energy_flux",  # Vertical integral of divergence of total energy flux, W m**-2
    "vertical_integral_of_divergence_of_ozone_flux",  # Vertical integral of divergence of ozone flux, kg m**-2 s**-1
    "vertical_integral_of_eastward_cloud_liquid_water_flux",  # Vertical integral of eastward cloud liquid water flux, kg m**-1 s**-1
    "vertical_integral_of_northward_cloud_liquid_water_flux",  # Vertical integral of northward cloud liquid water flux, kg m**-1 s**-1
    "vertical_integral_of_eastward_cloud_frozen_water_flux",  # Vertical integral of eastward cloud frozen water flux, kg m**-1 s**-1
    "vertical_integral_of_northward_cloud_frozen_water_flux",  # Vertical integral of northward cloud frozen water flux, kg m**-1 s**-1
    "vertical_integral_of_mass_tendency",  # Vertical integral of mass tendency, kg m**-2 s**-1
    "total_column_cloud_liquid_water",  # Total column cloud liquid water, kg m**-2
    "total_column_cloud_ice_water",  # Total column cloud ice water, kg m**-2
    "total_column_supercooled_liquid_water",  # Total column supercooled liquid water, kg m**-2
    "total_column_rain_water",  # Total column rain water, kg m**-2
    "total_column_snow_water",  # Total column snow water, kg m**-2
    "total_column_water",  # Total column water, kg m**-2
    "total_column_water_vapour",  # Total column water vapour, kg m**-2
    "total_column_ozone",  # Total column ozone, kg m**-2
    # Wave parameters: instantaneous
    "significant_wave_height_of_first_swell_partition",  # Significant wave height of first swell partition, m
    "mean_wave_direction_of_first_swell_partition",  # Mean wave direction of first swell partition, degrees
    "mean_wave_period_of_first_swell_partition",  # Mean wave period of first swell partition, s
    "significant_wave_height_of_second_swell_partition",  # Significant wave height of second swell partition, m
    "mean_wave_direction_of_second_swell_partition",  # Mean wave direction of second swell partition, degrees
    "mean_wave_period_of_second_swell_partition",  # Mean wave period of second swell partition, s
    "significant_wave_height_of_third_swell_partition",  # Significant wave height of third swell partition, m
    "mean_wave_direction_of_third_swell_partition",  # Mean wave direction of third swell partition, degrees
    "mean_wave_period_of_third_swell_partition",  # Mean wave period of third swell partition, s
    "wave_spectral_skewness",  # Wave Spectral Skewness, dimensionless
    "free_convective_velocity_over_the_oceans",  # Free convective velocity over the oceans, m s**-1
    "air_density_over_the_oceans",  # Air density over the oceans, kg m**-3
    "normalized_energy_flux_into_waves",  # Normalized energy flux into waves, dimensionless
    "normalized_energy_flux_into_ocean",  # Normalized energy flux into ocean, dimensionless
    "normalized_stress_into_ocean",  # Normalized stress into ocean, dimensionless
    "u_component_stokes_drift",  # U-component stokes drift, m s**-1
    "v_component_stokes_drift",  # V-component stokes drift, m s**-1
    "period_corresponding_to_maximum_individual_wave_height",  # Period corresponding to maximum individual wave height, s
    "maximum_individual_wave_height",  # Maximum individual wave height, m
    "model_bathymetry",  # Model bathymetry, m
    "mean_wave_period_based_on_first_moment",  # Mean wave period based on first moment, s
    "mean_zero_crossing_wave_period",  # Mean zero-crossing wave period, s
    "wave_spectral_directional_width",  # Wave spectral directional width, Radians
    "mean_wave_period_based_on_first_moment_for_wind_waves",  # Mean wave period based on first moment for wind waves, s
    "mean_wave_period_based_on_second_moment_for_wind_waves",  # Mean wave period based on second moment for wind waves, s
    "wave_spectral_directional_width_for_wind_waves",  # Wave spectral directional width for wind waves, Radians
    "mean_wave_period_based_on_first_moment_for_swell",  # Mean wave period based on first moment for swell, s
    "mean_wave_period_based_on_second_moment_for_swell",  # Mean wave period based on second moment for swell, s
    "wave_spectral_directional_width_for_swell",  # Wave spectral directional width for swell, Radians
    "significant_height_of_combined_wind_waves_and_swell",  # Significant height of combined wind waves and swell, m
    "mean_wave_direction",  # Mean wave direction, degrees
    "peak_wave_period",  # Peak wave period, s
    "mean_wave_period",  # Mean wave period, s
    "coefficient_of_drag_with_waves",  # Coefficient of drag with waves, dimensionless
    "significant_height_of_wind_waves",  # Significant height of wind waves, m
    "mean_direction_of_wind_waves",  # Mean direction of wind waves, degrees
    "mean_period_of_wind_waves",  # Mean period of wind waves, s
    "significant_height_of_total_swell",  # Significant height of total swell, m
    "mean_direction_of_total_swell",  # Mean direction of total swell, degrees
    "mean_period_of_total_swell",  # Mean period of total swell, s
    "mean_square_slope_of_waves",  # Mean square slope of waves, dimensionless
    "ocean_surface_stress_equivalent_10m_neutral_wind_speed",  # 10 metre wind speed, m s**-1
    "ocean_surface_stress_equivalent_10m_neutral_wind_direction",  # 10 metre wind direction, degrees
    "wave_spectral_kurtosis",  # Wave spectral kurtosis, dimensionless
    "benjamin_feir_index",  # Benjamin-Feir index, dimensionless
    "wave_spectral_peakedness",  # Wave spectral peakedness, dimensionless
}

# Pressure-level variables
ALL_PRESSURE_LEVEL_VARIABLES = {
    # Pressure level parameters: instantaneous
    "potential_vorticity",  # Potential vorticity, K m**2 kg**-1 s**-1
    "specific_rain_water_content",  # Specific rain water content, kg kg**-1
    "specific_snow_water_content",  # Specific snow water content, kg kg**-1
    "geopotential",  # Geopotential, m**2 s**-2
    "temperature",  # Temperature, K
    "u_component_of_wind",  # U component of wind, m s**-1
    "v_component_of_wind",  # V component of wind, m s**-1
    "specific_humidity",  # Specific humidity, kg kg**-1
    "vertical_velocity",  # Vertical velocity, Pa s**-1
    "vorticity",  # Vorticity (relative), s**-1
    "divergence",  # Divergence, s**-1
    "relative_humidity",  # Relative humidity, %
    "ozone_mass_mixing_ratio",  # Ozone mass mixing ratio, kg kg**-1
    "specific_cloud_liquid_water_content",  # Specific cloud liquid water content, kg kg**-1
    "specific_cloud_ice_water_content",  # Specific cloud ice water content, kg kg**-1
    "fraction_of_cloud_cover",  # Fraction of cloud cover, (0 - 1)
}

# Model-level variables
ALL_MODEL_LEVEL_VARIABLES = {
    # Model level parameters: instantaneous
    "specific_rain_water_content",  # Specific rain water content, kg kg**-1
    "specific_snow_water_content",  # Specific snow water content, kg kg**-1
    "eta-coordinate_vertical_velocity",  # Eta-coordinate vertical velocity, s**-1
    "geopotential",  # Geopotential, m**2 s**-2
    "temperature",  # Temperature, K
    "u_component_of_wind",  # U component of wind, m s**-1
    "v_component_of_wind",  # V component of wind, m s**-1
    "specific_humidity",  # Specific humidity, kg kg**-1
    "vertical_velocity",  # Vertical velocity, Pa s**-1
    "vorticity",  # Relative vorticity, s**-1
    "logarithm_of_surface_pressure",  # Logarithm of surface pressure, ~
    "divergence",  # Divergence, s**-1
    "ozone_mass_mixing_ratio",  # Ozone mass mixing ratio, kg kg**-1
    "specific_cloud_liquid_water_content",  # Specific cloud liquid water content, kg kg**-1
    "specific_cloud_ice_water_content",  # Specific cloud ice water content, kg kg**-1
    "fraction_of_cloud_cover",  # Fraction of cloud cover, (0 - 1)
}

# Invariant surface and single level variables
INVARIANT_VARIABLES = {
    # Surface and single level parameters: invariants (in time)
    "lake_cover",  # Lake cover, (0 - 1)
    "lake_depth",  # Lake depth, m
    "low_vegetation_cover",  # Low vegetation cover, (0 - 1)
    "high_vegetation_cover",  # High vegetation cover, (0 - 1)
    "type_of_low_vegetation",  # Type of low vegetation, ~
    "type_of_high_vegetation",  # Type of high vegetation, ~
    "soil_type",  # Soil type 1, ~
    "standard_deviation_of_filtered_subgrid_orography",  # Standard deviation of filtered subgrid orography, m
    "geopotential",  # Geopotential, m**2 s**-2
    "standard_deviation_of_orography",  # Standard deviation of sub-gridscale orography, ~
    "anisotropy_of_sub_gridscale_orography",  # Anisotropy of sub-gridscale orography, ~
    "angle_of_sub_gridscale_orography",  # Angle of sub-gridscale orography, radians
    "slope_of_sub_gridscale_orography",  # Slope of sub-gridscale orography, ~
    "land_sea_mask",  # Land-sea mask, (0 - 1)
}

# Default: 13 variables (8 single-level surface + 5 pressure-level atmospheric)
DEFAULT_VARIABLES = [
    # Single-level temperature, pressure and humidity
    "2m_temperature",
    "maximum_2m_temperature_since_previous_post_processing",
    "minimum_2m_temperature_since_previous_post_processing",
    "2m_dewpoint_temperature",
    "surface_pressure",
    "mean_sea_level_pressure",
    # Single-level wind
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "100m_u_component_of_wind",
    "100m_v_component_of_wind",
    "10m_wind_gust_since_previous_post_processing",
    "total_precipitation",
    "evaporation",
    # Single-level radiation and clouds
    "total_cloud_cover",
    "surface_solar_radiation_downwards",
    # 3D variables at pressure levels
    "temperature",
    "specific_humidity",
    "u_component_of_wind",
    "v_component_of_wind",
    "vertical_velocity",
    "geopotential",
]

# All available pressure levels in ERA5
ALL_PRESSURE_LEVELS = [
    "1",
    "2",
    "3",
    "5",
    "7",
    "10",
    "20",
    "30",
    "50",
    "70",
    "100",
    "125",
    "150",
    "175",
    "200",
    "225",
    "250",
    "300",
    "350",
    "400",
    "450",
    "500",
    "550",
    "600",
    "650",
    "700",
    "750",
    "775",
    "800",
    "825",
    "850",
    "875",
    "900",
    "925",
    "950",
    "975",
    "1000",
]

# Default: 1000, 975, 950 hPa (lowest 3 pressure levels, ~110m, ~300m, ~560m altitude)
DEFAULT_PRESSURE_LEVELS = ["1000", "975", "950"]

# All available model levels in ERA5 (1-137, where 137 is the surface)
ALL_MODEL_LEVELS = [str(i) for i in range(1, 138)]

# Default: 133, 134, 135, 136, 137 (lowest 5 model levels, ~150m, ~100-120m, ~50-70m, ~10-15m, surface)
DEFAULT_MODEL_LEVELS = ["133", "134", "135", "136", "137"]

# Mapping of variable names to MARS parameter short codes
VARIABLE_TO_MARS_PARAM = {
    # Surface and single level parameters: instantaneous
    "convective_inhibition": "cin",
    "friction_velocity": "zust",
    "lake_mix_layer_temperature": "lmlt",
    "lake_mix_layer_depth": "lmld",
    "lake_bottom_temperature": "lblt",
    "lake_total_layer_temperature": "ltlt",
    "lake_shape_factor": "lshf",
    "lake_ice_temperature": "lict",
    "lake_ice_depth": "licd",
    "uv_visible_albedo_for_direct_radiation": "aluvp",
    "minimum_vertical_gradient_of_refractivity_inside_trapping_layer": "dndzn",
    "uv_visible_albedo_for_diffuse_radiation": "aluvd",
    "mean_vertical_gradient_of_refractivity_inside_trapping_layer": "dndza",
    "near_ir_albedo_for_direct_radiation": "alnip",
    "duct_base_height": "dctb",
    "near_ir_albedo_for_diffuse_radiation": "alnid",
    "trapping_layer_base_height": "tplb",
    "trapping_layer_top_height": "tplt",
    "cloud_base_height": "cbh",
    "zero_degree_level": "deg0l",
    "instantaneous_10m_wind_gust": "i10fg",
    "sea_ice_cover": "ci",
    "snow_albedo": "asn",
    "snow_density": "rsn",
    "sea_surface_temperature": "sst",
    "ice_temperature_layer_1": "istl1",
    "ice_temperature_layer_2": "istl2",
    "ice_temperature_layer_3": "istl3",
    "ice_temperature_layer_4": "istl4",
    "volumetric_soil_water_layer_1": "swvl1",
    "volumetric_soil_water_layer_2": "swvl2",
    "volumetric_soil_water_layer_3": "swvl3",
    "volumetric_soil_water_layer_4": "swvl4",
    "convective_available_potential_energy": "cape",
    "leaf_area_index_low_vegetation": "lai_lv",
    "leaf_area_index_high_vegetation": "lai_hv",
    "10m_u_component_of_neutral_wind": "u10n",
    "10m_v_component_of_neutral_wind": "v10n",
    "surface_pressure": "sp",
    "soil_temperature_level_1": "stl1",
    "snow_depth": "sd",
    "charnock": "chnk",
    "mean_sea_level_pressure": "msl",
    "boundary_layer_height": "blh",
    "total_cloud_cover": "tcc",
    "10m_u_component_of_wind": "10u",
    "10m_v_component_of_wind": "10v",
    "2m_temperature": "2t",
    "2m_dewpoint_temperature": "2d",
    "soil_temperature_level_2": "stl2",
    "soil_temperature_level_3": "stl3",
    "low_cloud_cover": "lcc",
    "medium_cloud_cover": "mcc",
    "high_cloud_cover": "hcc",
    "skin_reservoir_content": "src",
    "instantaneous_large_scale_surface_precipitation_fraction": "ilspf",
    "convective_rain_rate": "crr",
    "large_scale_rain_rate": "lsrr",
    "convective_snowfall_rate_water_equivalent": "csfr",
    "large_scale_snowfall_rate_water_equivalent": "lssfr",
    "instantaneous_eastward_turbulent_surface_stress": "iews",
    "instantaneous_northward_turbulent_surface_stress": "inss",
    "instantaneous_surface_sensible_heat_flux": "ishf",
    "instantaneous_moisture_flux": "ie",
    "skin_temperature": "skt",
    "soil_temperature_level_4": "stl4",
    "temperature_of_snow_layer": "tsn",
    "forecast_albedo": "fal",
    "forecast_surface_roughness": "fsr",
    "forecast_logarithm_of_surface_roughness_for_heat": "flsr",
    "100m_u_component_of_wind": "100u",
    "100m_v_component_of_wind": "100v",
    "precipitation_type": "ptype",
    "k_index": "kx",
    "total_totals_index": "totalx",
    # Surface and single level parameters: accumulated
    "large_scale_precipitation_fraction": "lspf",
    "downward_uv_radiation_at_the_surface": "uvb",
    "boundary_layer_dissipation": "bld",
    "surface_sensible_heat_flux": "sshf",
    "surface_latent_heat_flux": "slhf",
    "surface_solar_radiation_downwards": "ssrd",
    "surface_thermal_radiation_downwards": "strd",
    "surface_net_solar_radiation": "ssr",
    "surface_net_thermal_radiation": "str",
    "top_net_solar_radiation": "tsr",
    "top_net_thermal_radiation": "ttr",
    "eastward_turbulent_surface_stress": "ewss",
    "northward_turbulent_surface_stress": "nsss",
    "eastward_gravity_wave_surface_stress": "lgws",
    "northward_gravity_wave_surface_stress": "mgws",
    "gravity_wave_dissipation": "gwd",
    "top_net_solar_radiation_clear_sky": "tsrc",
    "top_net_thermal_radiation_clear_sky": "ttrc",
    "surface_net_solar_radiation_clear_sky": "ssrc",
    "surface_net_thermal_radiation_clear_sky": "strc",
    "toa_incident_solar_radiation": "tisr",
    "vertically_integrated_moisture_divergence": "vimd",
    "total_sky_direct_solar_radiation_at_surface": "fdir",
    "clear_sky_direct_solar_radiation_at_surface": "cdir",
    "surface_solar_radiation_downward_clear_sky": "ssrdc",
    "surface_thermal_radiation_downward_clear_sky": "strdc",
    "surface_runoff": "sro",
    "sub_surface_runoff": "ssro",
    "snow_evaporation": "es",
    "snowmelt": "smlt",
    "large_scale_precipitation": "lsp",
    "convective_precipitation": "cp",
    "snowfall": "sf",
    "evaporation": "e",
    "runoff": "ro",
    "total_precipitation": "tp",
    "convective_snowfall": "csf",
    "large_scale_snowfall": "lsf",
    "potential_evaporation": "pev",
    # Surface and single level parameters: mean rates/fluxes
    "mean_surface_runoff_rate": "msror",
    "mean_sub_surface_runoff_rate": "mssror",
    "mean_snow_evaporation_rate": "mser",
    "mean_snowmelt_rate": "msmr",
    "mean_large_scale_precipitation_fraction": "mlspf",
    "mean_surface_downward_uv_radiation_flux": "msdwuvrf",
    "mean_large_scale_precipitation_rate": "mlspr",
    "mean_convective_precipitation_rate": "mcpr",
    "mean_snowfall_rate": "msr",
    "mean_boundary_layer_dissipation": "mbld",
    "mean_surface_sensible_heat_flux": "msshf",
    "mean_surface_latent_heat_flux": "mslhf",
    "mean_surface_downward_short_wave_radiation_flux": "msdwswrf",
    "mean_surface_downward_long_wave_radiation_flux": "msdwlwrf",
    "mean_surface_net_short_wave_radiation_flux": "msnswrf",
    "mean_surface_net_long_wave_radiation_flux": "msnlwrf",
    "mean_top_net_short_wave_radiation_flux": "mtnswrf",
    "mean_top_net_long_wave_radiation_flux": "mtnlwrf",
    "mean_eastward_turbulent_surface_stress": "metss",
    "mean_northward_turbulent_surface_stress": "mntss",
    "mean_evaporation_rate": "mer",
    "mean_eastward_gravity_wave_surface_stress": "megwss",
    "mean_northward_gravity_wave_surface_stress": "mngwss",
    "mean_gravity_wave_dissipation": "mgwd",
    "mean_runoff_rate": "mror",
    "mean_top_net_short_wave_radiation_flux_clear_sky": "mtnswrfcs",
    "mean_top_net_long_wave_radiation_flux_clear_sky": "mtnlwrfcs",
    "mean_surface_net_short_wave_radiation_flux_clear_sky": "msnswrfcs",
    "mean_surface_net_long_wave_radiation_flux_clear_sky": "msnlwrfcs",
    "mean_top_downward_short_wave_radiation_flux": "mtdwswrf",
    "mean_vertically_integrated_moisture_divergence": "mvimd",
    "mean_total_precipitation_rate": "mtpr",
    "mean_convective_snowfall_rate": "mcsr",
    "mean_large_scale_snowfall_rate": "mlssr",
    "mean_surface_direct_short_wave_radiation_flux": "msdrswrf",
    "mean_surface_direct_short_wave_radiation_flux_clear_sky": "msdrswrfcs",
    "mean_surface_downward_short_wave_radiation_flux_clear_sky": "msdwswrfcs",
    "mean_surface_downward_long_wave_radiation_flux_clear_sky": "msdwlwrfcs",
    "mean_potential_evaporation_rate": "mper",
    # Surface and single level parameters: minimum/maximum
    "10m_wind_gust_since_previous_post_processing": "10fg",
    "maximum_2m_temperature_since_previous_post_processing": "mx2t",
    "minimum_2m_temperature_since_previous_post_processing": "mn2t",
    "maximum_total_precipitation_rate_since_previous_post_processing": "mxtpr",
    "minimum_total_precipitation_rate_since_previous_post_processing": "mntpr",
    # Surface and single level parameters: vertical integrals and total column: instantaneous
    "vertical_integral_of_mass_of_atmosphere": "vima",
    "vertical_integral_of_temperature": "vit",
    "vertical_integral_of_kinetic_energy": "vike",
    "vertical_integral_of_thermal_energy": "vithe",
    "vertical_integral_of_potential_and_internal_energy": "vipie",
    "vertical_integral_of_potential_internal_and_latent_energy": "vipile",
    "vertical_integral_of_total_energy": "vitoe",
    "vertical_integral_of_energy_conversion": "viec",
    "vertical_integral_of_eastward_mass_flux": "vimae",
    "vertical_integral_of_northward_mass_flux": "viman",
    "vertical_integral_of_eastward_kinetic_energy_flux": "vikee",
    "vertical_integral_of_northward_kinetic_energy_flux": "viken",
    "vertical_integral_of_eastward_heat_flux": "vithee",
    "vertical_integral_of_northward_heat_flux": "vithen",
    "vertical_integral_of_eastward_water_vapour_flux": "viwve",
    "vertical_integral_of_northward_water_vapour_flux": "viwvn",
    "vertical_integral_of_eastward_geopotential_flux": "vige",
    "vertical_integral_of_northward_geopotential_flux": "vign",
    "vertical_integral_of_eastward_total_energy_flux": "vitoee",
    "vertical_integral_of_northward_total_energy_flux": "vitoen",
    "vertical_integral_of_eastward_ozone_flux": "vioze",
    "vertical_integral_of_northward_ozone_flux": "viozn",
    "vertical_integral_of_divergence_of_cloud_liquid_water_flux": "vilwd",
    "vertical_integral_of_divergence_of_cloud_frozen_water_flux": "viiwd",
    "vertical_integral_of_divergence_of_mass_flux": "vimad",
    "vertical_integral_of_divergence_of_kinetic_energy_flux": "viked",
    "vertical_integral_of_divergence_of_thermal_energy_flux": "vithed",
    "vertical_integral_of_divergence_of_moisture_flux": "viwvd",
    "vertical_integral_of_divergence_of_geopotential_flux": "vigd",
    "vertical_integral_of_divergence_of_total_energy_flux": "vitoed",
    "vertical_integral_of_divergence_of_ozone_flux": "viozd",
    "vertical_integral_of_eastward_cloud_liquid_water_flux": "vilwe",
    "vertical_integral_of_northward_cloud_liquid_water_flux": "vilwn",
    "vertical_integral_of_eastward_cloud_frozen_water_flux": "viiwe",
    "vertical_integral_of_northward_cloud_frozen_water_flux": "viiwn",
    "vertical_integral_of_mass_tendency": "vimat",
    "total_column_cloud_liquid_water": "tclw",
    "total_column_cloud_ice_water": "tciw",
    "total_column_supercooled_liquid_water": "tcslw",
    "total_column_rain_water": "tcrw",
    "total_column_snow_water": "tcsw",
    "total_column_water": "tcw",
    "total_column_water_vapour": "tcwv",
    "total_column_ozone": "tco3",
    # Wave parameters: instantaneous
    "significant_wave_height_of_first_swell_partition": "swh1",
    "mean_wave_direction_of_first_swell_partition": "mwd1",
    "mean_wave_period_of_first_swell_partition": "mwp1",
    "significant_wave_height_of_second_swell_partition": "swh2",
    "mean_wave_direction_of_second_swell_partition": "mwd2",
    "mean_wave_period_of_second_swell_partition": "mwp2",
    "significant_wave_height_of_third_swell_partition": "swh3",
    "mean_wave_direction_of_third_swell_partition": "mwd3",
    "mean_wave_period_of_third_swell_partition": "mwp3",
    "wave_spectral_skewness": "wss",
    "free_convective_velocity_over_the_oceans": "wstar",
    "air_density_over_the_oceans": "rhoao",
    "normalized_energy_flux_into_waves": "phiaw",
    "normalized_energy_flux_into_ocean": "phioc",
    "normalized_stress_into_ocean": "tauoc",
    "u_component_stokes_drift": "ust",
    "v_component_stokes_drift": "vst",
    "period_corresponding_to_maximum_individual_wave_height": "tmax",
    "maximum_individual_wave_height": "hmax",
    "model_bathymetry": "wmb",
    "mean_wave_period_based_on_first_moment": "mp1",
    "mean_zero_crossing_wave_period": "mp2",
    "wave_spectral_directional_width": "wdw",
    "mean_wave_period_based_on_first_moment_for_wind_waves": "p1ww",
    "mean_wave_period_based_on_second_moment_for_wind_waves": "p2ww",
    "wave_spectral_directional_width_for_wind_waves": "dwww",
    "mean_wave_period_based_on_first_moment_for_swell": "p1ps",
    "mean_wave_period_based_on_second_moment_for_swell": "p2ps",
    "wave_spectral_directional_width_for_swell": "dwps",
    "significant_height_of_combined_wind_waves_and_swell": "swh",
    "mean_wave_direction": "mwd",
    "peak_wave_period": "pp1d",
    "mean_wave_period": "mwp",
    "coefficient_of_drag_with_waves": "cdww",
    "significant_height_of_wind_waves": "shww",
    "mean_direction_of_wind_waves": "mdww",
    "mean_period_of_wind_waves": "mpww",
    "significant_height_of_total_swell": "shts",
    "mean_direction_of_total_swell": "mdts",
    "mean_period_of_total_swell": "mpts",
    "mean_square_slope_of_waves": "msqs",
    "ocean_surface_stress_equivalent_10m_neutral_wind_speed": "wind",
    "ocean_surface_stress_equivalent_10m_neutral_wind_direction": "dwi",
    "wave_spectral_kurtosis": "wsk",
    "benjamin_feir_index": "bfi",
    "wave_spectral_peakedness": "wsp",
    # Pressure level parameters: instantaneous
    "potential_vorticity": "pv",
    "specific_rain_water_content": "crwc",
    "specific_snow_water_content": "cswc",
    "geopotential": "z",
    "temperature": "t",
    "u_component_of_wind": "u",
    "v_component_of_wind": "v",
    "specific_humidity": "q",
    "vertical_velocity": "w",
    "vorticity": "vo",
    "divergence": "d",
    "relative_humidity": "r",
    "ozone_mass_mixing_ratio": "o3",
    "specific_cloud_liquid_water_content": "clwc",
    "specific_cloud_ice_water_content": "ciwc",
    "fraction_of_cloud_cover": "cc",
    # Model level parameters: instantaneous (additional to pressure level parameters)
    "eta-coordinate_vertical_velocity": "etadot",
    "logarithm_of_surface_pressure": "lnsp",
    # Surface and single level parameters: invariants (in time)
    "lake_cover": "cl",
    "lake_depth": "dl",
    "low_vegetation_cover": "cvl",
    "high_vegetation_cover": "cvh",
    "type_of_low_vegetation": "tvl",
    "type_of_high_vegetation": "tvh",
    "soil_type": "slt",
    "standard_deviation_of_filtered_subgrid_orography": "sdfor",
    "standard_deviation_of_orography": "sdor",
    "anisotropy_of_sub_gridscale_orography": "isor",
    "angle_of_sub_gridscale_orography": "anor",
    "slope_of_sub_gridscale_orography": "slor",
    "land_sea_mask": "lsm",
}


# TypedDicts for model configurationurations for MARS and CDS APIs
class _CDSConfig(TypedDict):
    product_type: list[str]
    download_format: str
    data_format: str
    dataset_pl: str
    dataset_sl: str


class _MARSConfig(TypedDict):
    dataset: str
    mars_class: str
    mars_stream: str
    mars_type: str
    mars_expver: str
    levtype_model: str


class _ModelConfig(TypedDict):
    url: str
    start_year: str
    MARS: _MARSConfig
    CDS: _CDSConfig


MODEL_CONFIG: _ModelConfig = {
    "url": "https://cds.climate.copernicus.eu/api",
    "start_year": "1940",
    "MARS": {
        "dataset": "reanalysis-era5-complete",
        "mars_class": "ea",
        "mars_stream": "oper",
        "mars_type": "an",
        "mars_expver": "1",
        "levtype_model": "ml",
    },
    "CDS": {
        "product_type": ["reanalysis"],
        "download_format": "unarchived",
        "data_format": "grib",
        "dataset_pl": "reanalysis-era5-pressure-levels",
        "dataset_sl": "reanalysis-era5-single-levels",
    },
}
