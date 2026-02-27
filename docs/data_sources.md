# Data Source Catalogue

This document provides an overview of sources for both energy generation
and meteorological data that can be downloaded and processed via the
RenewBench-Crawler package.

## Energy

### Overview

| Region                   | Source   | Status             | Resolution               | Access            | Resources                                                                                                                                                                                                                                                                                                 |
|--------------------------|----------|--------------------|--------------------------|-------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Europe**               | ENTSO-e  | downloader &check; | hourly/15 min; per plant | API token         | [TP](https://transparency.entsoe.eu/), [API guide](https://transparencyplatform.zendesk.com/hc/en-us/sections/12783116987028-Restful-API-integration-guide),<br> [API how-to](https://transparencyplatform.zendesk.com/hc/en-us/articles/12845911031188-How-to-get-security-token)                        |
| **Turkey**               | EPIAS    | downloader &check; | hourly; per plant        | Login credentials | [TP](https://seffaflik.epias.com.tr/home), [Docs](https://seffaflik.epias.com.tr/electricity-service/technical/en/index.html),<br> [Registration form](https://kayit.epias.com.tr/epias-transparency-platform-registration-form)                                                                          |
| **USA**                  | EIA      | downloader &check; | hourly; per company      | API token         | [API browser](https://www.eia.gov/opendata/browser/), [API docs](https://www.eia.gov/opendata/documentation.php),<br> [API registration form](https://www.eia.gov/opendata/register.php)                                                                                                                  |
| **Taiwan**               | Taipower | downloader &check; | 10 min; per plant        | public            | [Website](https://www.taipower.com.tw/d006/loadGraph/loadGraph/genshx_e.html), [JSON](https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/genary_eng.json),<br> [Example parser](https://github.com/electricitymaps/electricitymaps-contrib/blob/master/electricitymap/contrib/parsers/TAIPOWER.py) |
| **Canada<br> (Alberta)** | IESO     | planned            |                          |                   |                                                                                                                                                                                                                                                                                                           |
| **Canada<br> (Ontario)** | AESO     | planned            |                          |                   |                                                                                                                                                                                                                                                                                                           |
| **Chile**                | CEN      | planned            |                          |                   |                                                                                                                                                                                                                                                                                                           |
| **Brazil**               | ONS      | planned            |                          |                   |                                                                                                                                                                                                                                                                                                           |
| **Uruguay**              | ADME     | planned            |                          |                   |                                                                                                                                                                                                                                                                                                           |
| **Australia**            | AEMO     | planned            |                          |                   |                                                                                                                                                                                                                                                                                                           |
| **New<br>Zealand**       | EAT      | planned            |                          |                   |                                                                                                                                                                                                                                                                                                           |

### Data Source Details

<details>
<summary><b>ENTSO-e (Europe)</b></summary>

**Access**
- Platform: [ENTSO-e Transparency Platform](https://transparency.entsoe.eu/)
- Docs: [RESTful API integration guide](https://transparencyplatform.zendesk.com/hc/en-us/sections/12783116987028-Restful-API-integration-guide)
- Requirements: personal API token ([how to get a token](https://transparencyplatform.zendesk.com/hc/en-us/articles/12845911031188-How-to-get-security-token))

**Download & data structure**
- Resolution: hourly / 15 min (stored as `Temporal_Resolution`), per plant and bidding zone
- Raw output files: 1 CSV per day and bidding zone
- Raw columns:

  `timestamp`, `Unit_Name`, `Unit_Code`, `PSR_Type`, `Capacity`, `Generation_MW`,
  `Consumption_MW`, `Measurement_Unit`, `Temporal_Resolution`

</details>

<details>
<summary><b>EPIAS (Turkey)</b></summary>

**Access**
- Platform: [EPIAS Transparency Platform](https://seffaflik.epias.com.tr/home)
- Docs: [Technical documentation](https://seffaflik.epias.com.tr/electricity-service/technical/en/index.html)
- Requirements: personal username/password ([registration form](https://kayit.epias.com.tr/epias-transparency-platform-registration-form))

**Download & data structure**
- Resolution: hourly, per plant
- Raw output files: 1 CSV per day
- Raw columns (simplified):

  `date`, `hour`, `total`, `powerPlantName`,
  `naturalGas`, `dammedHydro`, `lignite`, `river`, `importCoal`, `wind`, `sun`,
  `fueloil`, `geothermal`, `asphaltiteCoal`, `blackCoal`, `biomass`, `naphta`, `lng`,
  `importExport`, `wasteheat`.

</details>

<details>
<summary><b>EIA (USA)</b></summary>

**Access**
- Platform: [EIA API browser](https://www.eia.gov/opendata/browser/)
- Docs: [EIA API documentation](https://www.eia.gov/opendata/documentation.php)
- Requirements: personal API token ([registration form](https://www.eia.gov/opendata/register.php))

**Download & data structure**
- Resolution: hourly, per company
- Raw output files: 1 CSV per day
- Raw columns:

  `period`, `respondent`, `respondent-name`, `fueltype`, `type-name`, `value`,
  `value-units`

</details>

<details>
<summary><b>Taipower (Taiwan)</b></summary>

**Access**
- Website: [Live generation page](https://www.taipower.com.tw/d006/loadGraph/loadGraph/genshx_e.html)
- JSON endpoint: [Generation data](https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/genary_eng.json)
- Example parser: [electricitymaps Taipower parser](https://github.com/electricitymaps/electricitymaps-contrib/blob/master/electricitymap/contrib/parsers/TAIPOWER.py)
- Requirements: public, no authentication needed

**Download & data structure**
- Resolution: 10 min (live data)
- Raw output files: 1 CSV per snapshot timestamp
- Raw columns:

  `datetime`, `fueltype`, `fueltype_subcategory`, `name`, `capacity`, `output`,
  `percentage`, `remark_xi`, `additional_3`

</details>

## Weather

### Overview

| Region | Source            | Status             | Resolution             | Access    | Resources                                                                                                                                                                                                                                                 |
|--------|-------------------|--------------------|------------------------|-----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| World  | ERA5              | downloader &check; | 0.25° (~31 km); hourly | API token | [Copernicus / ECMWF](https://apps.ecmwf.int/data-catalogues/era5/?type=an&class=ea&stream=oper&expver=1),<br> [Download guide](https://confluence.ecmwf.int/display/CKB/How+to+download+ERA5), [API how-to](https://cds.climate.copernicus.eu/how-to-api) |
| World  | ICON DREAM Global | downloader &check; | ~13 km; hourly         | open      | [DWD Open Data](https://opendata.dwd.de/climate_environment/REA/ICON-DREAM-Global/hourly/), [Guide](http://dx.doi.org/10.5676/dwd/icon-dream_v1)                                                                                                          |
| Europe | ICON DREAM Europe | downloader &check; | ~6.5 km; hourly        | open      | [DWD Open Data](https://opendata.dwd.de/climate_environment/REA/ICON-DREAM-EU/hourly/), [Guide](http://dx.doi.org/10.5676/dwd/icon-dream_v1)                                                                                                              |

### Data Source Details

<details>
<summary><b>ERA5 (World)</b></summary>

**Access**
- Platform: [Copernicus Climate Data Store / ECMWF](https://cds.climate.copernicus.eu/)
- Dataset example: [ERA5 reanalysis data catalogue](https://apps.ecmwf.int/data-catalogues/era5/?type=an&class=ea&stream=oper&expver=1)
- Docs: [How to download ERA5](https://confluence.ecmwf.int/display/CKB/How+to+download+ERA5)
- Requirements: personal CDS API key ([how to get a token](https://cds.climate.copernicus.eu/how-to-api))

**Download & data structure**
- Resolution: typically 0.25° × 0.25° (~31 km) global grid, hourly data
- Spatial coverage: global by default; optional subset via a bounding box (`area` parameter)
- Levels:
  - Single-level (surface/2D variables)
  - Pressure levels (3D fields on 37 pressure levels)
  - Model levels (3D fields on 137 hybrid sigma-pressure levels)
- Raw output files (as implemented here):
  - Format: GRIB or NetCDF (`file_format` option), extension `.grib` or `.nc`
  - One file per year–month, level type (single/pressure/model) and group of variables
- Key dimensions & variables (conceptual):
  - Dimensions: `time`, `latitude`, `longitude`, optional `level`
  - Variables: user-selected ERA5 variables (e.g. temperature, wind components, humidity, geopotential, etc.)

</details>

<details>
<summary><b>ICON-DREAM Global (World)</b></summary>

**Access**
- Platform: [DWD Open Data – ICON-DREAM Global hourly](https://opendata.dwd.de/climate_environment/REA/ICON-DREAM-Global/hourly/)
- Docs / reference: [ICON-DREAM reanalysis guide](http://dx.doi.org/10.5676/dwd/icon-dream_v1)
- Requirements: open HTTP access (no authentication)

**Download & data structure**
- Resolution: ~13 km (unstructured grid), hourly data
- Spatial coverage: global
- Levels:
  - Single-level (surface/2D variables)
  - Model levels (10 lowest 3D fields of 120 full-level (121 half-level) on hybrid sigma-height vertical coordinates)
- Raw output files (as implemented here):
  - Format: GRIB (`*.grb`)
  - Naming: `ICON-DREAM-Global_<YYYY><MM>_<CODE>_hourly.grb`
  - One file per year–month and variable (parameter code), per region
- Grid metadata (downloaded separately via `download_metadata`):
  - Grid definition: `icon_grid_0026_R03B07_G.nc`
  - Grid refinement information: `icon_grid_0026_R03B07_G-grfinfo.nc`
- Key dimensions & variables (conceptual):
  - Dimensions: time, gridpoint index (icosahedral grid)
  - Variables: user-selected ICON-DREAM variables (surface and model-level fields)

</details>

<details>
<summary><b>ICON-DREAM Europe</b></summary>

**Access**
- Platform: [DWD Open Data – ICON-DREAM EU hourly](https://opendata.dwd.de/climate_environment/REA/ICON-DREAM-EU/hourly/)
- Docs / reference: [ICON-DREAM reanalysis guide](http://dx.doi.org/10.5676/dwd/icon-dream_v1)
- Requirements: open HTTP access (no authentication)

**Download & data structure**
- Resolution: ~6.5 km (icosahedral ICON grid), hourly data
- Spatial coverage: Europe
- Levels:
  - Single-level (surface/2D variables)
  - Model levels (10 lowest 3D fields of 120 full-level (121 half-level) on hybrid sigma-height vertical coordinates)
- Raw output files (as implemented here):
  - Format: GRIB (`*.grb`)
  - Naming: `ICON-DREAM-EU_<YYYY><MM>_<CODE>_hourly.grb`
  - One file per year–month and variable (parameter code), per region
- Grid metadata (downloaded separately via `download_metadata`):
  - Grid definition: `icon_grid_0027_R03B08_N02.nc`
  - Grid refinement information: `icon_grid_0027_R03B08_N02-grfinfo.nc`
- Key dimensions & variables (conceptual):
  - Dimensions: time, gridpoint index (unstructured grid)
  - Variables: user-selected ICON-DREAM variables (2D single level and 3D model level)

</details>
