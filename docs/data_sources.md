# Data Source Catalogue

This document provides an overview of sources for both energy generation
and meteorological data that can be downloaded and processed via the
RenewBench-Crawler package.

## Energy

### Overview

| Region                   | Source   | Status             | Resolution               | Access            | Resources                                                                                                                                                                                                                                                                                                              |
|--------------------------|----------|--------------------|--------------------------|-------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Europe**               | ENTSO-e  | downloader &check; | hourly/15 min; per plant | API token         | [TP](https://transparency.entsoe.eu/), [API guide](https://transparencyplatform.zendesk.com/hc/en-us/sections/12783116987028-Restful-API-integration-guide),<br> [API how-to](https://transparencyplatform.zendesk.com/hc/en-us/articles/12845911031188-How-to-get-security-token)                                     |
| **Turkey**               | EPIAS    | downloader &check; | hourly; per plant        | Login credentials | [TP](https://seffaflik.epias.com.tr/home), [Docs](https://seffaflik.epias.com.tr/electricity-service/technical/en/index.html),<br> [Registration form](https://kayit.epias.com.tr/epias-transparency-platform-registration-form)                                                                                       |
| **USA**                  | EIA      | downloader &check; | hourly; per company      | API token         | [API browser](https://www.eia.gov/opendata/browser/), [API docs](https://www.eia.gov/opendata/documentation.php),<br> [API registration form](https://www.eia.gov/opendata/register.php)                                                                                                                               |
| **Canada<br> (Alberta)** | AESO     | downloader &check; | hourly/5 min; per plant  | `box` API token   | [Website](https://www.aeso.ca/market/market-and-system-reporting/data-requests/historical-generation-data/), [Data hosting](https://aeso.app.box.com/s/qofgn9axnnw6uq3ip1goiq2ngb11txe5/folder/196731538687), <br> [API how-to](https://developer.box.com/guides/authentication/tokens/developer-tokens) (s. details!) |
| **Canada<br> (Ontario)** | IESO     | downloader &check; | hourly; per plant        | public            | [Website](https://www.ieso.ca/power-data/data-directory)                                                                                                                                                                                                                                                               |
| **Chile**                | CEN      | planned            |                          |                   |                                                                                                                                                                                                                                                                                                                        |
| **Brazil**               | ONS      | planned            |                          |                   |                                                                                                                                                                                                                                                                                                                        |
| **Uruguay**              | ADME     | planned            |                          |                   |                                                                                                                                                                                                                                                                                                                        |
| **Australia**            | AEMO     | planned            |                          |                   |                                                                                                                                                                                                                                                                                                                        |
| **New<br>Zealand**       | EAT      | planned            |                          |                   |                                                                                                                                                                                                                                                                                                                        |
| **Japan**                | REI      | planned            | hourly; per region       |                   |                                                                                                                                                                                                                                                                                                                        |
| **Taiwan**               | Taipower | downloader &check; | 10 min; per plant        | public            | [Website](https://www.taipower.com.tw/d006/loadGraph/loadGraph/genshx_e.html), [JSON](https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/genary_eng.json),<br> [Example parser](https://github.com/electricitymaps/electricitymaps-contrib/blob/master/electricitymap/contrib/parsers/TAIPOWER.py)              |

### Data Source Details

<details>
<summary><b>ENTSO-e (Europe)</b></summary>

**Access**
- Platform: [ENTSO-e Transparency Platform](https://transparency.entsoe.eu/)
- Docs: [RESTful API integration guide](https://transparencyplatform.zendesk.com/hc/en-us/sections/12783116987028-Restful-API-integration-guide)
- Requirements: personal API token ([how to get a token](https://transparencyplatform.zendesk.com/hc/en-us/articles/12845911031188-How-to-get-security-token))

**Download & data structure**
- Spatial resolution: per generation unit (plant) in each bidding zone
- Temporal resolution: hourly / (sometimes) higher
- Available data timespan: bidding zone dependant (typically mid‑2010s to now - see
  [`ACTIVE_ZONES_METADATA` mapping](../rbc/energy/entsoe/mappings.py#L6))
- Files saved as **raw**: 1 `.csv` per day and bidding zone
- Columns saved as **raw**:

  `timestamp` – timestamp start in UTC-aware (`+00:00`)

  `Unit_Name` – name of the generating unit

  `Unit_Code` – unique identifier (mRID) of the generating unit

  `PSR_Type` – PSR code of fuel category

  `Capacity` – nominal capacity of the generating unit

  `Generation_MW` – actual generation in MW

  `Consumption_MW` – consumption in MW (if the unit is consuming, else `NaN`)

  `Measurement_Unit` – physical unit of the reported quantities (usually `MAW`)

  `Temporal_Resolution` – string describing the time step (e.g. `PT15M`, `PT60M`)

</details>

<details>
<summary><b>EPIAS (Turkey)</b></summary>

**Access**
- Platform: [EPIAS Transparency Platform](https://seffaflik.epias.com.tr/home)
- Docs: [Technical documentation](https://seffaflik.epias.com.tr/electricity-service/technical/en/index.html)
- Requirements: personal username/password ([registration form](https://kayit.epias.com.tr/epias-transparency-platform-registration-form))

**Download & data structure**
- Spatial resolution: per plant
- Temporal resolution: hourly
- Available data timespan: 2013-05 to now
- Files saved as **raw**: 1 `.csv` per day
- Columns saved as **raw**:

  `date` – timestamp start in UTC-aware (`+03:00`)

  `hour` – hour

  `total` – total generation of the power plant (MWh)

  `powerPlantName` – name of the power plant

  `naturalGas`, `dammedHydro`, `lignite`, `river`, `importCoal`, `wind`, `sun`,
  `fueloil`, `geothermal`, `asphaltiteCoal`, `blackCoal`, `biomass`, `naphta`, `lng`,
  `importExport`, `wasteheat` - generation from different sources

</details>

<details>
<summary><b>EIA (USA)</b></summary>

**Access**
- Platform: [EIA API browser](https://www.eia.gov/opendata/browser/)
- Docs: [EIA API documentation](https://www.eia.gov/opendata/documentation.php)
- Requirements: personal API token ([registration form](https://www.eia.gov/opendata/register.php))

**Download & data structure**
- Spatial resolution: per respondent (company)
- Temporal resolution: hourly
- Available data timespan: 2019-01 to now
- Files saved as **raw**: 1 `.csv` per day
- Columns saved as **raw**:

  `period` - timestamp start in UTC

  `respondent` - abbreviation for respondent (company) name

  `respondent-name` - full respondent (company) name

  `fueltype` - abbreviation for fuel categorization

  `type-name` - full fuel name

  `value` - net generation

  `value-units` - unit of net generation

</details>


<details>
<summary><b>AESO (Canada, Alberta)</b></summary>

**Access**
- Website: [AESO historical data](https://www.aeso.ca/market/market-and-system-reporting/data-requests/historical-generation-data/), [AESO
  'box' data hosting/storage](https://aeso.app.box.com/s/qofgn9axnnw6uq3ip1goiq2ngb11txe5/folder/196731538687)
- Requirements:
  1. Create a free [box account](https://app.box.com/developers/console/).
  2. In [the console](https://app.box.com/developers/console), create a new app with `App
  Type` as `OAuth 2.0` (`App name` is irrelevant).
  3. In the app's configuration
     - Under `Application Scopes`: tick the box `Write all files and folders stored in
     Box` and save.
     - Under `Developer Token`: click the `Generate Developer Token` button or directly
       copy the existing token. This is your API token!

**Download & data structure**
- Spatial resolution: per plant
- Temporal resolution: hourly / 5 min
- Available data timespan hourly: 2015-01 to now; 5 min: 2015-01 to 2023-02
- Downloadable files: 1 `.zip` containing 1 `.csv` per month / 6-month periods
- Files saved as **raw**: 1 `.csv` per month
- Columns saved as **raw**:

  `Date (MST)` - timestamp start in Mountain Standard Time

  `Date (MPT)` - timestamp start in Mountain Prevailing Time (i.e. MST or MDT, as appropriate)

  `Asset Short Name` - abbreviation for asset

  `Asset Name` - asset name

  `Asset Grouping` - the meter that behind-the-fence assets share, if appropriate.

  `Volume` - volume reported via SCADA (similar to that reported on CSD page)

  `Maximum Capability` - maximum capacity reported to the AESO

  `System Capability` - capacity available to AESO via contracted volume, if any

  `Fuel Type` - main fuel categorization

  `Sub Fuel Type` - sub fuel categorization

  `Planning Area` - AESO planning area the asset is located in

  `Region` - AESO region the asset is located in

</details>


<details>
<summary><b>IESO (Canada, Ontario)</b></summary>

**Access**
- Website: [IESO power data](https://www.ieso.ca/power-data/data-directory), [IESO supply overview](https://www.ieso.ca/Power-Data/Supply-Overview/Transmission-Connected-Generation)
- Map: [Ontario's Electricity System](https://www.ieso.ca/localcontent/ontarioenergymap/index.html)
- Requirements: public, no authentication needed

**Download & data structure**
- Spatial resolution: per plant
- Temporal resolution: hourly
- Available data timespan: 2010-01 to now
- Downloadable files: 1 `.xlsx` per year (pre-April-2019), 1 `.csv` per month (post-April-2019)
- Files saved as **raw**: 1 `.csv` per month
- Columns saved as **raw**:

  `Delivery Date` – date in local format (probably ET)

  `Generator` – generator name

  `Fuel Type` – fuel type (not given in `.xlsx` so `=NaN`; to be filled in during processing)

  `Measurement` – type of measurement:
  - `Output`: generation (MW)
  - `Capability`: available capacity

  `Hour 1`, `Hour 2`, …, `Hour 24` – ending hour intervals (i.e. `00:00 - 01:00` to `23:00 to
  00:00`) and measurement type

</details>

<details>
<summary><b>Taipower (Taiwan)</b></summary>

**Access**
- Website: [Live generation page](https://www.taipower.com.tw/d006/loadGraph/loadGraph/genshx_e.html)
- JSON endpoint: [Generation data](https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/genary_eng.json)
- Example parser: [electricitymaps Taipower parser](https://github.com/electricitymaps/electricitymaps-contrib/blob/master/electricitymap/contrib/parsers/TAIPOWER.py)
- Requirements: public, no authentication needed

**Download & data structure**
- Spatial resolution: per plant
- Temporal resolution: 10 min (live data)
- Available data timespan: 2026-02 to now
- Files saved as **raw**: 1 `.csv` per snapshot timestamp
- Columns saved as **raw**:

  `datetime` – timestamp in UTC-aware fixed-offset ISO 8601 (`+08:00`)

  `fueltype` – fuel type (e.g. `COAL`, `GAS`, `NUCLEAR`, `HYDRO`, `PV`)

  `fueltype_subcategory` – fuel type sub‑category for renewables (i.e. purchases)

  `name` – generating unit

  `capacity` – installed nameplate capacity (nominal capacity of a plant or sum of capacities
  of all plants in a unit)

  `output` – net power generation (amount generated by a unit = total gross generation −
  power consumption within the plant)

  `percentage` – output relative to capacity (`output / capacity`) (%)

  `remark_xi` – numbers referring to specific Taipower remarks wherever necessary

  `additional_3` – additional remarks field

</details>


### Saving Structure

The downloaded, raw energy data is saved into the following structure per data source
`<source>`. Values in `()` are optional, i.e. only `entsoe` has a `<bidding_zone>`
hierarchy level.

```text
raw/energy
└── <source>
    ├── status.pickle
    ├── logs
    │   └── <YYYY-MM-DD_HHMMSS>.log
    └── <temporal_resolution (default: "1h")>
        └── (<bidding_zone>)
            └── <YYYY-MM(-DD)>.csv
```

## Weather

### Overview

| Region | Resolution | Source | Platform                                                                                        | Docs                                                                                 | Access    | How-to                                                             |
| ------ | ------ | ------ |-------------------------------------------------------------------------------------------------| ------------------------------------------------------------------------------------ | --------- | ------------------------------------------------------------------ |
| Global | 0.25° / ~31km; 1 hour | ERA5   | [Copernicus / ECMWF](https://apps.ecmwf.int/data-catalogues/era5/?type=an&class=ea&stream=oper&expver=1) | [Data download guide](https://confluence.ecmwf.int/display/CKB/How+to+download+ERA5) | API token | [Installation guide](https://cds.climate.copernicus.eu/how-to-api) |
| Global | ~13km; 1 hour | ICON DREAM Global   | [DWD](https://opendata.dwd.de/climate_environment/REA/ICON-DREAM-Global/hourly/) | [Guide](http://dx.doi.org/10.5676/dwd/icon-dream_v1) | open | - |
| Europe | ~6.5km; 1 hour |ICON DREAM Europe  | [DWD](https://opendata.dwd.de/climate_environment/REA/ICON-DREAM-EU/hourly/) | [Guide](http://dx.doi.org/10.5676/dwd/icon-dream_v1) | open | - |
| Australia and surroundings | 0.11° / ~11km; 1 hour | BARRA2 R2 | [BOM](https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/catalog.html) | [Guide](https://opus.nci.org.au/spaces/NDP/pages/264241166/BOM+BARRA2+ob53) | open | - |
| Australia | 0.04° / ~4km; 1 hour | BARRA2 C2 | [BOM](https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/1hr/catalog.html) | [Guide](https://opus.nci.org.au/spaces/NDP/pages/264241166/BOM+BARRA2+ob53) | open | - |
| Australia | 0.04° / ~4km; 20 min | BARRA2 C2 | [BOM](https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/20min/catalog.html) | [Guide](https://opus.nci.org.au/spaces/NDP/pages/264241166/BOM+BARRA2+ob53) | open | - |

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

<details>
<summary><b>BARRA2 (Australia)</b></summary>

**Access**
- Platform: [NCI THREDDS server](https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/)
- Docs / reference: [BOM BARRA2 guide](https://opus.nci.org.au/spaces/NDP/pages/264241166/BOM+BARRA2+ob53)
- Requirements: open HTTP access (no authentication)


**Download & data structure**

BARRA2 is a regional reanalysis produced by the Australian Bureau of Meteorology (BOM), downscaling ERA5 over Australia and surrounding regions. Three model configurations are supported:

| Model key  | Grid label | Nominal resolution | Temporal resolution | Coverage start |
|------------|------------|--------------------|---------------------|----------------|
| `R2`       | AUS-11     | ~11 km             | 1 hour              | 1979           |
| `C2`       | AUST-04    | ~4 km              | 1 hour              | 1991           |
| `C2_20min` | AUST-04    | ~4 km              | 20 min              | 1991           |


- Spatial coverage:
  - R2: Australia and surrounding region (~11 km, `AUS-11` grid)
  - C2 / C2_20min: Australia only (~4 km, `AUST-04` grid)
- Levels:
  - Single-level (surface / 2D variables, the majority of variables)
  - Pressure levels (3D fields; R2: 39 levels, C2: 16 levels)
  - Invariant (time-independent fields: orography, land-sea mask)
- Raw output files (as implemented here):
  - Format: NetCDF (`*.nc`), fetched via HTTP from NCI THREDDS fileServer
  - Temporal files: `barra2_<MODEL>_<TEMPORAL_RES>_<YYYYMM>_<BARRA2_CODE>.nc`
  - Invariant files: `barra2_<MODEL>_fx_<BARRA2_CODE>.nc` (downloaded once, stored in `invariant/` subfolder)
  - One file per year–month and variable; invariants are model-wide constants
- Key dimensions & variables (conceptual):
  - Dimensions: `time`, `lat`, `lon`, optional `lev` (pressure level)
  - Default variables: `tas` (1.5 m temperature), `pr` (precipitation), `uas` / `vas` (10 m wind components), `rsds` (surface downwelling shortwave radiation), `ps` (surface pressure), `huss` (specific humidity)
  - Additional variables selectable by name (use `--list-variables` to see available codes per model)

</details>
