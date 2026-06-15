# Data Source Catalogue

This document provides an overview of sources for both energy generation
and meteorological data that can be downloaded and processed via the
RenewBench-Crawler package.

## Energy

### Overview

| Region                   | Source   | Status             | Resolution               | Access            | Resources                                                                                                                                                                                                                                                                                                              |
|--------------------------|----------|--------------------|--------------------------|-------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Europe**               | ENTSO-e  | downloader &check; | hourly/higher; per plant | API token         | [TP](https://transparency.entsoe.eu/), [API guide](https://transparencyplatform.zendesk.com/hc/en-us/sections/12783116987028-Restful-API-integration-guide),<br> [API how-to](https://transparencyplatform.zendesk.com/hc/en-us/articles/12845911031188-How-to-get-security-token)                                     |
| **Turkey**               | EPIAS    | downloader &check; | hourly; per plant        | Login credentials | [TP](https://seffaflik.epias.com.tr/home), [Docs](https://seffaflik.epias.com.tr/electricity-service/technical/en/index.html),<br> [Registration form](https://kayit.epias.com.tr/epias-transparency-platform-registration-form)                                                                                       |
| **USA**                  | EIA      | downloader &check; | hourly; per company      | API token         | [API browser](https://www.eia.gov/opendata/browser/), [API docs](https://www.eia.gov/opendata/documentation.php),<br> [API registration form](https://www.eia.gov/opendata/register.php)                                                                                                                               |
| **Canada<br> (Alberta)** | AESO     | downloader &check; | hourly/5 min; per plant  | `box` API token   | [Website](https://www.aeso.ca/market/market-and-system-reporting/data-requests/historical-generation-data/), [Data hosting](https://aeso.app.box.com/s/qofgn9axnnw6uq3ip1goiq2ngb11txe5/folder/196731538687), <br> [API how-to](https://developer.box.com/guides/authentication/tokens/developer-tokens) (s. details!) |
| **Canada<br> (Ontario)** | IESO     | downloader &check; | hourly; per plant        | public            | [Website](https://www.ieso.ca/power-data/data-directory)                                                                                                                                                                                                                                                               |
| **Chile**                | CEN      | downloader &check; | hourly; per plant        | API token         | [Website](https://www.coordinador.cl/reportes-y-estadisticas/#Estadisticas), [API site](https://portal.api.coordinador.cl/documentacion?service=sipubv2), <br> [API usage docs](https://cartas.coordinador.cl/download_anexos/66c7447c35635715c87c4271/0)                                                              |
| **Brazil**               | ONS      | downloader &check; | hourly; per plant        | public            | [Website](https://dados.ons.org.br/dataset/geracao-usina-2), Data hosting on AWS S3                                                                                                                                                                                                                                    |
| **Uruguay**              | ADME     | downloader &check; | hourly; per plant        | public            | [Website](https://www.adme.com.uy/controlpanel.php), Data hosting [old](https://www.adme.com.uy/gpf_historico.php) / [new](https://www.adme.com.uy/panelControl/gpf.php)                                                                                                                                               |
| **Australia**            | AEMO     | downloader &check; | hourly/5 min; per plant  | API token         | [Website](https://www.aemo.com.au/),<br> [Python package](https://github.com/opennem/openelectricity-python), [API docs](https://docs.openelectricity.org.au/)                                                                                                                                                         |
| **New<br>Zealand**       | EAT      | downloader &check; | 30 min; per plant        | public            | [Website / Data hosting](https://www.ea.govt.nz/data-and-insights/datasets/wholesale/generation/generation-output/)                                                                                                                                                                                                    |
| **Japan**                | REI      | planned            | hourly; per region       | public            | [Website](https://www.renewable-ei.org/en/activities/statistics/20200619.php), [Dashboard](https://www.renewable-ei.org/en/statistics/electricity/#demand),<br> [Example JSON for 2020](https://www.renewable-ei.org/en/statistics/electricity/data/2020/power-data.json)                                              |
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

  `timestamp` – timestamp start in UTC-aware ISO 8601 (`YYYY-MM-DDTHH:MM:SS+00:00`)

  `time_series.mkt_psrtype.power_system_resources.name` – name of the generating unit

  `time_series.mkt_psrtype.power_system_resources.m_rid.value` – unique identifier (mRID) of the generating unit

  `time_series.mkt_psrtype.psr_type` – PSR code of fuel category

  `time_series.mkt_psrtype.power_system_resources.nominal_p` – nominal capacity of the generating unit

  `time_series.period.point.quantity` – actual generation in MW

  `time_series.period.point.secondary_quantity` – consumption in MW (if the unit is consuming, else `NaN`)

  `time_series.quantity_measure_unit_name` – physical unit of the reported quantities
  (usually `MAW`). According to [their TP docs](https://transparencyplatform.zendesk.com/hc/en-us/articles/16648326220564-Actual-Generation-per-Generation-Unit-16-1-A):
  "Average of all available instantaneous net power output values in each Market Time Unit."
  => MWh if `time_series.period.resolution = PT60M` (= 1h)

  `time_series.period.resolution` – string describing the time step (e.g. `PT15M`, `PT60M`)

**STAC**

- `measurement_type`: `'net_output'`
  - According to [their TP docs](https://transparencyplatform.zendesk.com/hc/en-us/articles/16648326220564-Actual-Generation-per-Generation-Unit-16-1-A):
    "Actual net generation output (MW) per market time unit and per generation unit of 100
    MW or more installed generation capacity. "

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

  `date` – timestamp start in UTC-aware ISO 8601 (`YYYY-MM-DDTHH:MM:SS+03:00`)

  `hour` – hour

  `total` – total generation of the power plant in MWh

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

  `period` - timestamp start in UTC naive ISO 8601 (`YYYY-MM-DDTHH`)

  `respondent` - abbreviation for respondent (company) name

  `respondent-name` - full respondent (company) name

  `fueltype` - abbreviation for fuel categorization

  `type-name` - full fuel name

  `value` - net generation

  `value-units` - unit of net generation (commonly MWh)

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

  `Date (MST)` - timestamp start in Mountain Standard Time in local format (`YYYY-MM-DD HH:MM:SS`)

  `Date (MPT)` - timestamp start in Mountain Prevailing Time (i.e. MST or MDT, as appropriate)

  `Asset Short Name` - abbreviation for asset

  `Asset Name` - asset name

  `Asset Grouping` - the meter that behind-the-fence assets share, if appropriate.

  `Volume` - volume reported via SCADA (similar to that reported on CSD page). According to
  [their website](https://www.aeso.ca/market/market-and-system-reporting/data-requests/historical-generation-data/):
  "The reported volume is the average generation over the given period." = MWh

  `Maximum Capability` - maximum capacity reported to the AESO

  `System Capability` - capacity available to AESO via contracted volume, if any

  `Fuel Type` - main fuel categorization

  `Sub Fuel Type` - sub fuel categorization

  `Planning Area` - AESO planning area the asset is located in

  `Region` - AESO region the asset is located in

**STAC**

- `measurement_type`: `'gross_output'`
  -  According to [their website](https://www.aeso.ca/market/market-and-system-reporting/data-requests/historical-generation-data/):
    "\[...\] this data is not the same as settlement meter data.
    This data generally represents what was generated at the unit, not necessarily
    what is delivered to the AESO grid."

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
- Downloadable files: 1 `.xlsx` per year (before April-2019), 1 `.csv` per month
  (from April-2019 onwards)
- Files saved as **raw**: 1 `.csv` per month
- Columns saved as **raw**:

  `Delivery Date` – date in local format (`YYYY-MM-DD`)

  `Generator` – generator name

  `Fuel Type` – fuel type (not given in `.xlsx` so `=NaN`; to be filled in during processing)

  `Measurement` – type of measurement:
  - `Output`: generation in MW. According to [their docs](https://reports-public.ieso.ca/docrefs/helpfile/GenOutputCapability_h4.pdf):
    "Output is the actual energy production of the unit or facility. The hourly output is the facility’s five-minute
     outputs averaged over an hour." => MWh
  - `Capability`: available capacity

  `Hour 1`, `Hour 2`, …, `Hour 24` – ending hour intervals (i.e. `00:00 - 01:00` to `23:00 to
  00:00`) and measurement type

</details>


<details>
<summary><b>CEN (Chile)</b></summary>

**Access**
- Website: [CEN Website](https://www.coordinador.cl/reportes-y-estadisticas/#Estadisticas), generation data
   [archive (= "old")](https://www.coordinador.cl/reportes-y-estadisticas/#Estadisticas) and
   [current (= "new")](https://www.coordinador.cl/operacion/graficos/operacion-real/generacion-real/),
   [API guide](https://www.coordinador.cl/wp-content/uploads/2019/01/Uso-Api-SIP-Sistema-Informacion-Publica-v1.1.pdf)
   and [API site](https://portal.api.coordinador.cl/documentacion?service=sipubv2)
- Requirements: "old" data needs no authentification, but all data available via API,
  which needs a personal API token
  1. Sign up to the [coordinador portal](https://portal.api.coordinador.cl/signup).
     - Select the "Información Pública (SIP)" plan
  2. After confirming signup, login and navigate to
     [the "Planes" tab](https://portal.api.coordinador.cl/planes), go to the field
     "Plan Consulta de Datos Información Pública (SIP)" and press the button "Suscribirse
     a Unidata(es) de Negocio". Confirm by pressing the red "Suscribirse" button. You
     should now be part of the buisness unit.
  3. In the "Planes" tab, the field "Plan Consulta de Datos Información Pública (SIP)" now
     has the new button "Suscribirse al plan" button. Click on it, fill out the
     required information - insert a name (`Nombre`) for your application/token and a
     description (`Descripción`) detailling what it's for - and press the button "Crear
     Aplicación".
  4. The new window will show a field "Clave de usuario" with a long alphanumeric
     string. This is your API token!
- Limitations: 60 queries per hour
- License: ? (s. terms and conditions of API account registration)

**Download & data structure**
- Spatial resolution: per plant
- Temporal resolution: hourly
- Available data timespan: 2000 to now
- Downloadable files: 1 `.xlsx` per multiple years / year (until 2025), API data
- Files saved as **raw**: 1 `.csv` per day
- Columns saved as **raw**:

  `id_opreal` - internal operation record identifier

  `llave_opreal` - unique operational real-time key/hash

  `id_central` - power plant identifier

  `central` - power plant name

  `gen_real_mw` - real generation in MW

  `fecha_hora` - timestamp start in local format (`YYYY-MM-DD HH:MM:SS`)

  `hora` - hour of the day (1 to 24)

  `potencia_maxima` - maximum capacity or gross maximum power of the plant in MW

  `id_propietario` - asset owner/company identifier

  `propietario` - name of the asset owner/company that owns the plant

  `id_coordinado` - coordinated entity identifier (operator/legal entity registered with CEN)

  `coordinado` - name of the coordinated entity/operator

  `tipo_tecnologia` - technology type (e.g. `Térmico`, `Hidráulica`, etc)

  `subtipo_tecnologia` - technology subtype (e.g. `Retiro`, `Inyección`, `Embalse`, etc)

  `factor_ernc` - ERNC factor (indicates if the technology qualifies as Non-Conventional Renewable Energy)

  `alcance` - scope classification (`global` or `partial`)

  `valor_ernc` - ERNC compliance value or generation contribution qualified under renewable targets

**STAC**

- `measurement_type`: `'?_gross_output'`

  No definitive proof for "as generated" (total gross production on-site, not net grid
  injections) could be found, but:
  - According to [the CNE](https://www.cne.cl/wp-content/uploads/2025/01/NTSyCS-Ene-2025.pdf):
    - "Coordinated entities must supply the Coordinator with all Real-Time information deemed
       necessary for the proper coordination of SI Real-Time operations."
    - "the minimum set of variables to be monitored shall be as follows: a) Net active
       power injected by each unit into the SI."
  - According to the [API documentation](https://www.coordinador.cl/wp-content/uploads/2019/01/Uso-Api-SIP-Sistema-Informacion-Publica-v1.1.pdf):
    "All endpoints shall deliver raw data—that is, data without aggregations or
     transformations applied to the values ​​stored in the database."
- `entity_type`: `'unit'` (?)

  No definitive proof, but the data indicates this in two ways:
  - values for `central` showing same name with different numbers, i.e. `'BESS Andes'`,
    `'BESS Andes IV'`
  - there are more unique `id_opreal` values than `central` names than unique `id_central`
    values

</details>


<details>
<summary><b>ONS (Brazil)</b></summary>

**Access**
- Website: [ONS generation data](https://dados.ons.org.br/dataset/geracao-usina-2)
- Requirements: public, no authentication needed
- License: [CC Attribution](https://dados.ons.org.br/dataset/geracao-usina-2)

**Download & data structure**
- Spatial resolution: per plant
- Temporal resolution: hourly
- Available data timespan: 2000 to now
- Downloadable files: 1 `.csv` (or `.xlsx`) per year (before 2022), 1 `.csv` (or `.xlsx`) per
  month (from 2022 onwards)
- Files saved as **raw**: 1 `.csv` per month
- Columns saved as **raw**:

  `din_instante` - timestamp start in local format (`YYYY-MM-DD HH:MM:SS`)

  `id_subsistema` - subsystem identifier (3-character code for Brazilian grid subsystem)

  `nom_subsistema` - name of the subsystem

  `id_estado` - state identifier (2-character code for Brazilian state)

  `nom_estado` - name of the state where the plant is located

  `cod_modalidadeoperacao` - plant operation mode (e.g. type of operational dispatch)

  `nom_tipousina` - plant type (e.g. hydro, thermal, wind, solar)

  `nom_tipocombustivel` - fuel type used by the plant

  `nom_usina` - name of the power plant

  `id_ons` - unique identifier assigned by ONS (National System Operator)

  `ceg` - unique generation project identifier assigned by ANEEL (Brazilian regulator)

  `val_geracao` - generation in MWmed (average MW over the time interval; equivalent to MWh for hourly data)

</details>


<details>
<summary><b>ADME (Uruguay)</b></summary>

**Access**
- Website: [ADME Website](https://www.adme.com.uy/controlpanel.php), generation data hosting
  [archive (= "old")](https://www.adme.com.uy/gpf_historico.php) and [current (= "new")](https://www.adme.com.uy/panelControl/gpf.php)
- Requirements: public, no authentication needed

**Download & data structure**
- Spatial resolution: per plant
- Temporal resolution: hourly
- Available data timespan: 2009 to now
- Downloadable files: 1 `.xlsx` per year (before 2019), 1 `.csv` (or `.xlsx`) per
  month (from 2019 onwards)
- Files saved as **raw**: 1 `.csv` per month
- Columns saved as **raw**:

  `(/, Fecha)` – timestamp end (!) in local format (`DD-MM-YYYY HH:MM`)

  `(Hidráulico, <unit_name>)`, `(Biomasa, <unit_name>)`, `(Térmico, <unit_name>)`,
  `(Eólico, <unit_name>)`, `(Solar, <unit_name>)` - generation per plant and source in MWh.
  According to [their website](https://adme-com-uy.translate.goog/datosabiertos.html?_x_tr_sl=es&_x_tr_tl=en&_x_tr_hl=en-US&_x_tr_pto=wapp):
  "The file contains hourly data series showing the generation in MW of the different power plants"

> **PLEASE NOTE:**
>
> The times are stored in an End-of-Interval format that will require conversion! Also,
> the data is stored with a MultiIndex (double) column header!

</details>

<details>
<summary><b>AEMO (Australia)</b></summary>

**Access**
- Platform: [OpenElectricity](https://platform.openelectricity.org.au/)
- Docs: [OpenElectricity Rest API](https://docs.openelectricity.org.au/api-reference/overview),
  [Facility data guide](https://docs.openelectricity.org.au/guides/facilities)
- Requirements: personal API token
  1. Create account for the OpenElectricity platform via the [sign-up](https://platform.openelectricity.org.au/sign-up)
  2. Go to Dashboard > API Keys > "+ Create New Key". This is your API token.
- Limits: for 5-min data, max 8 days at once; for hourly data, max 32 days at once
- License: [CC BY-NC 4.0](https://docs.openelectricity.org.au/api-reference/overview#data-licence)

**Download & data structure**
- Spatial resolution: per generation unit (plant)
- Temporal resolution: hourly / 5 min
- Available data timespan: 1998 to now
- Files saved as **raw**: 1 `.csv` per day for 5-min, 1 `.csv` per month for 1h
- Columns saved as **raw**:

  `timestamp` – timestamp end (!) in UTC-aware ISO 8601 (`YYYY-MM-DDTHH:MM:SS+00:00`;
  `+10:00` for NEM, `+08:00` for WEM)

  `code` – facility code

  `name` – facility name

  `network_id` – AEMO network identifier (e.g. `NEM`, `WEM`, `AU`)

  `network_region` – network region identifier (e.g. `NSW1`, `QLD1`, `SA1`)

  `description` – free-text facility description (HTML stripped)

  `location` – location dict of the facility (i.e. `{'lat': ..., 'lng': ...}`)

  `unit_code` – unique unit name (starts with facility name)

  `unit_fueltech_id` – fuel/technology classification of the unit

  `unit_status_id` – status of the unit (e.g. operating, retired)

  `unit_dispatch_type` – dispatch type of the unit (e.g. `GENERATOR`, `LOAD`)

  `unit_capacity_registered` – registered capacity of the unit (probably MW)

  `unit_capacity_maximum` – maximum capacity of the unit (probably MW)

  `unit_capacity_storage` – storage capacity of the unit

  `unit_data_first_seen` – first date the unit appears in AEMO / OpenElectricity data

  `unit_data_last_seen` – last date the unit appears in AEMO / OpenElectricity data

  `unit_commencement_date` – official commencement date of the unit

  `value` – energy generated in the interval (MWh), derived from AEMO power data

> **PLEASE NOTE:**
>
> The times are stored in an End-of-Interval format that will require conversion!
> (s. [the docs](https://docs.openelectricity.org.au/guides/curtailment#understanding-aemo%E2%80%99s-timestamp-convention))
>
> The stored energy generation/load values in MWh are calculated from AEMO's power data
> (for more information, s. [their docs](https://docs.openelectricity.org.au/guides/energy#difference-between-energy-and-power))
> All data is based on 5-min instantaneous power \[MW\], meaning hourly values are always
> aggregated. For power, this aggregration is erroneously done by summation.
> [An issue](https://github.com/opennem/opennem/issues/523) was created to address this.
> Energy seems to be independent of this problem.

**STAC**

- `measurement_type`: `'curtailed_gross_output'`
  - According to [OpenElectricity](https://docs.openelectricity.org.au/guides/curtailment#how-open-electricity-reports-curtailment):
    Curtailment is not included directly in the data but can theoretically be accessed
    separately. This is not done here.
  - AEMO publishes [SCADA data](https://www.nemweb.com.au/Reports/), which is
    ["power dispatch data"](https://docs.openelectricity.org.au/guides/power#data) parsed
    directly by [OpenElectricity](https://github.com/opennem/opennem/blob/main/opennem/crawl.py#L44).
    According to [AEMO's term definitions](https://www.aemo.com.au/-/media/files/electricity/nem/planning_and_forecasting/demand-forecasts/operational-consumption-definition.pdf),
    their provided [generation output](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/market-management-system-mms-data/generation-and-load)
    seems to be "as generated" (total gross production on-site, not net grid injections).
- `entity_type`: `'unit'`

  The parsed data is specifically for units. These all are associated with a facility
  (under `code` and `name`) for which consolidated data is generated in postprocessing to
  create `entity_type`: `'facility'` rows.

</details>

<details>
<summary><b>EAT (New Zealand)</b></summary>

**Access**
- Website: [EA Te-Mana-Hiko power data](https://www.ea.govt.nz/data-and-insights/datasets/wholesale/generation/generation-output/)
- Requirements: public, no authentication needed

**Download & data structure**
- Spatial resolution: per plant
- Temporal resolution: 30 min
- Available data timespan: 1997-08 to now
- Downloadable files: 1 `.csv` per month
- Files saved as **raw**: 1 `.csv` per month
- Columns saved as **raw**:

  `site_code` – ?

  `poc_code` – the point of connection on the grid at which injections occur (three-letter
  code denoting geographic location)

  `nwk_code` – the network code

  `gen_code` – a name given to the plant

  `fuel_code` – the fuel type used at the plant

  `tech_code` – the plant technology

  `trading_date` – the date on which the injections occurred (YYYY-MM-DD)

  `tp1`, `tp2`, …, `tp50` – generation values in kWh (!) per trading period, starting at
  midnight in half hour intervals. **NOTE:** Daylight saving is applied (46 TP = on
  the day saving starts, 50 TP = on the day it ends)

> **PLEASE NOTE:**
>
> The EA website states: "This data series will be replaced by one that is more reliable and
> contains a richer set of plant metadata at some point in the future."
>
> This will likely affect data parsing when it is implemented, but for now things work...

</details>


<details>
<summary><b>REI (Japan)</b></summary>

**Access**
- Website: [REI info site](https://www.renewable-ei.org/en/activities/statistics/20200619.php), [REI data dashboard](https://www.renewable-ei.org/en/statistics/electricity/#demand)
- Requirements: public, no authentication needed
- License: unclear, but [they state](https://www.renewable-ei.org/en/activities/statistics/20200619.php):

  "You can use the downloaded figures and data freely.
  However, when citing, please use the credit notation in the following form: [...]"

**Download & data structure**
- Spatial resolution: per [region](https://github.com/RenewBench-Association/RenewBench-Crawler/blob/main/rbc/energy/rei/downloader.py#L28)
  (!)
- Temporal resolution: hourly
- Available data timespan: April 2016 to (two months before) now
- Downloadable files: 1 `.json` per year
- Files saved as **raw**: 1 `.json` per month
- Keys saved as **raw**:

  `epochs: list` – timestamp start in [UNIX time](https://note.nkmk.me/en/python-unix-time-datetime/)

  `<region_name>: dict` – region as dict key, i.e. 'hokkaido', 'tohoku', 'tokyo', 'chubu',
  'hokuriku', 'kansai', 'chugoku', 'shikoku', and 'kyushu'.
  - `<fuel_type>: value` – the power generated by a specific fuel type in GW

> **PLEASE NOTE:**
>
> Data only available PER REGION!
>
> From 2024 onwards, the fuel types become more nuanced, such as the subdivision of
> 'thermal' into 'thermal_lng', 'thermal_oil', etc. These are therefore not explicitly
> checked during raw data storage.

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

  `datetime` – timestamp start in UTC-aware ISO 8601 (`YYYY-MM-DDTHH:MM:SS+08:00`)

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

| Region                     | Source / Model    | Status              | Resolution             | Data availability |  Access   |  Resources                                                                                                                                                                                                                                                 |
|----------------------------|-------------------|---------------------|------------------------|-------------------|-----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Australia and surroundings | BARRA2 R2         | downloader &check;  | 0.11° / ~11 km; hourly | 1979-present      | public    | [BOM](https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/catalog.html) [Guide](https://opus.nci.org.au/spaces/NDP/pages/264241166/BOM+BARRA2+ob53) |
| Australia                  | BARRA2 C2         | downloader &check;  | 0.04° / ~4 km; hourly  | 1979-present      | public    | [BOM](https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/1hr/catalog.html) [Guide](https://opus.nci.org.au/spaces/NDP/pages/264241166/BOM+BARRA2+ob53) |
| Australia                  | BARRA2 C2         | downloader &check;  | 0.04° / ~4 km; 20 min  | 1979-present      | public    | [BOM](https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/20min/catalog.html) [Guide](https://opus.nci.org.au/spaces/NDP/pages/264241166/BOM+BARRA2+ob53) |
| Global                     | ERA5              | downloader &check;  | 0.25° (~31 km); hourly | 1940–present      | API token | [Copernicus / ECMWF](https://apps.ecmwf.int/data-catalogues/era5/?type=an&class=ea&stream=oper&expver=1),<br> [Guide](https://confluence.ecmwf.int/display/CKB/How+to+download+ERA5), [API how-to](https://cds.climate.copernicus.eu/how-to-api) |
| Global                     | ICON DREAM Global | downloader &check;  | ~13 km; hourly         | 2010–present      | public    | [DWD Open Data](https://opendata.dwd.de/climate_environment/REA/ICON-DREAM-Global/hourly/), [Guide](http://dx.doi.org/10.5676/dwd/icon-dream_v1) |
| Europe                     | ICON DREAM Europe | downloader &check;  | ~6.5 km; hourly        | 2010–present      | public    | [DWD Open Data](https://opendata.dwd.de/climate_environment/REA/ICON-DREAM-EU/hourly/), [Guide](http://dx.doi.org/10.5676/dwd/icon-dream_v1) |


### Data Source Details

<details>
<summary><b>BARRA2</b></summary>

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


<details>
<summary><b>ERA5</b></summary>

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
<summary><b>ICON-DREAM Global</b></summary>

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

### Saving Structure

The downloaded, raw weather data is saved into the following structure per data source
`<source>`. Values in `()` are optional. For example, ICON DREAM has a `<model>` name of either 'global' or 'eu'.

```text
raw/weather
└── <source>
    ├── logs
    │    └── <YYYY-MM-DD_HHMMSS>.log
    └── (<model>)
        ├── status.pickle
        ├── <source_(model_)(temporal_resolution_)YYYYMM_variable_name>.nc/.grib
        └── (invariant)
            └── (invariant_variable.nc)
```

# Excluded Data Sources
This section lists energy and meteorological sources that are currently ineligible for integration or fall outside the functional scope of the RenewBench-Crawler package.

## Energy

An energy data source is excluded if it fails to meet **any** of the following criteria:
1. Spatial resolution finer than "state/country" level (e.g., must be per plant, per
   company, or per small area)
2. Temporal resolution of at least 1 hour (hourly or sub-hourly)
3. Data based on actual historical observations (not purely simulated generation)
4. Publicly accessible without restrictive publication prohibitions

| Region          | Source      | Status                                                 | Resolution                            | Data availability | Source                                                                                                                    |
|-----------------|-------------|--------------------------------------------------------|---------------------------------------|-------------------|---------------------------------------------------------------------------------------------------------------------------|
| World           | IEA         | Spatial and temporal resolutions too low, inaccessible | Per country; **yearly**               | 2000 – 2024       | [Platform](https://www.iea.org/data-and-statistics/data-tools/renewable-energy-progress-tracker)                          |
| World           | IRENA       | Spatial and temporal resolutions too low               | Per country; **yearly**               | 2000 – 2024       | [Data hosting](https://www.irena.org/Data/Downloads/IRENASTAT)                                                            |
| India           | CEA         | Spatial and temporal resolutions too low               | Per state (<=350,000 km²); **monthly** | 2019 – now        | [Dashboard](https://cea.nic.in/dashboard/?lang=en)                                                                        |
| Paraguay        | ANDE        | Spatial and temporal resolutions too low               | Per country (~400,000 km²); **yearly** | 1996 – 2019       | [Report](https://ande.gov.py/documentos_contables/706/ande_-_compilacion_estadistica_1999-2019.pdf)                       |
| Mexico          | CENACE      | Spatial resolution too low                             | Per country (~2,000,000 km²); hourly  | 2016 – now        | [Platform](https://www.cenace.gob.mx/Paginas/SIM/Reportes/EnergiaGeneradaTipoTec.aspx)                                    |
| South Africa    | Eskom       | Spatial resolution too low                             | Per country (~1,000,000 km²); hourly  | 2021 – now        | [Dashboard](https://www.eskom.co.za/dataportal/supply-side/station-build-up-for-the-last-7-days/)                         |
| South Korea     | KPX         | Spatial resolution too low                             | Per country (~100,000 km²); 5 min     | 2022 – now        | [Website](https://www.eskom.co.za/dataportal/supply-side/station-build-up-for-the-last-7-days/)                           |
| Europe          | EMHIRES     | Spatial resolution too low, simulated data!            | Per country; hourly                   | 2006 – now        | [Dataset](https://new.kpx.or.kr/powerSource.es?mid=a10606030000&device=chart)                                             |
| Canada (Quebec) | hydroquebec | Spatial resolution too low, only hydro data            | Per state (~500 km²); hourly           | 2018 – now        | [Dataset](https://donnees.hydroquebec.com/explore/dataset/historique-production-consommation-proxy-horaire/information/)  |
| Israel          | NOGA        | Unknown (site inaccessible from Europe / via VPN)      | Unknown                               | Unknown           | [Website](https://www.noga.co.il/)                                                                                        |

### Regions lacking data
- Africa: [All countries except South Africa](https://ember-energy.org/app/uploads/2024/10/African-Electricity-Data-Transparency.pdf)
- Middle East: Saudi Arabia, Bahrain, Qatar
- Asia: China, Indonesia, Philippines

### Geopolitical exclusions (data trustworthiness)
- Russia

## Weather

A reanalysis dataset is excluded if it fails to meet **any** of the following criteria:
1. Spatial resolution equal to or finer than ERA5 (grid spacing ≤ 0.25°)
2. Temporal resolution of at least 1 hour (hourly or sub-hourly)
3. Actively updated through at least the end of 2025

| Region              | Source / Model         | Status                                                                                                 | Resolution                   | Data availability | Resources |
|---------------------|------------------------|--------------------------------------------------------------------------------------------------------|------------------------------|-------------------|-----------|
| N. Hemisphere       | ASR                    | Temporal resolution too low (>1 hour); Outdated (no update since 2012)                                 | 15–30 km; 3-hourly           | 2000–2012         | [NCAR RDA](https://rda.ucar.edu/datasets/ds631.1/), [polarmet](http://polarmet.osu.edu/ASR/) |
| Australia / SE Asia | BARRA                  | Outdated (no update since 2019)                                                                        | 1.5 - 12 km; hourly          | 1990–2019         | [BOM](https://www.bom.gov.au/government-and-industry/research-and-development/research-and-development-projects/atmospheric-reanalysis#bom-anchor-list__item-available-barra-data) |
| Global              | CERA-20C               | Resolution too low (>0.25°); Temporal resolution too low (>1 hour); Outdated (no update since 2010)    | ~125 km (TL159); 3-hourly    | 1901–2010         | [ECMWF](https://www.ecmwf.int/en/forecasts/dataset/coupled-reanalysis-20th-century) |
| Global              | CORe                   | Resolution too low (>0.25°); Temporal resolution too low (>1 hour); Operational/public release unclear | 512x256 grid; 3-hourly       | 1950-2021         | [NOAA/CPC](https://www.cpc.ncep.noaa.gov/products/CORe) |
| Central Europe      | COSMO-REA2             | Outdated (no update since 2013)                                                                        | 2 km; hourly                 | 2007–2013         | [Uni Bonn](https://reanalysis.meteo.uni-bonn.de/?Download_Data___COSMO-REA2) |
| Europe              | COSMO-REA6             | Outdated (no update since 2018)                                                                        | 6.2 km; hourly               | 1995–2019         | [Uni Bonn](https://reanalysis.meteo.uni-bonn.de/?Download_Data___COSMO-REA6) |
| Global              | CMA CRA1.5             | Outdated (no update since 2024)                                                                        | 0.1° (~13 km); hourly        | 1979–2024         | [CMA](https://data.cma.cn/ai/#/detail?id=1), [Article](http://jmr.cmsjournal.net/article/doi/10.1007/s13351-025-5112-3) |
| Denmark             | DANRA                  | Temporal resolution too low (>1 hour)                                                                  | ~2.5 km; 3-hourly            | ~1990–present     | [DMIDK](https://dmidk.github.io/danradocs/intro.html)                          |
| Global              | ERA-15                 | Resolution too low (>0.25°); Temporal resolution too low (>1 hour); Outdated (no update since 1993)    | ~190 km (T106); 6-hourly     | 1979–1993         | [CEDA](https://catalogue.ceda.ac.uk/uuid/73ec447ea99457c77c0ef9692f76393f/) |
| Global              | ERA-20C                | Resolution too low (>0.25°); Temporal resolution too low (>1 hour); Outdated (no update since 2010)    | ~125 km (T159); 3-hourly     | 1900–2010         | [NCAR](https://gdex.ucar.edu/datasets/d626000/) |
| Global              | ERA-40                 | Resolution too low (>0.25°); Temporal resolution too low (>1 hour); Outdated (no update since 2002)    | ~125 km (T159); 6-hourly     | 1957–2002         | [ECMWF](https://www.ecmwf.int/en/elibrary/75291-era-40-archive-revised-october-2007) |
| Global              | ERA-Interim            | Resolution too low (>0.25°); Temporal resolution too low (>1 hour); Outdated (no update since 2019)    | ~80 km (T255); 3–6-hourly    | 1979–2019         | [ECMWF](https://www.ecmwf.int/en/forecasts/dataset/ecmwf-reanalysis-interim) |
| Global              | JRA-25                 | Resolution too low (>0.25°); Temporal resolution too low (>1 hour); Outdated (no update since 2014)    | ~110 km; 6-hourly            | 1979–2014         | [NCAR](https://rda.ucar.edu/datasets/ds625.0/) |
| Global              | JRA-3Q                 | Resolution too low (>0.25°); Temporal resolution too low (>1 hour)                                     | ~40 km (TL479L100); 3-hourly | 1947–present      | [NCAR](https://rda.ucar.edu/datasets/ds640-1/) |
| Global              | JRA-55                 | Resolution too low (>0.25°); Temporal resolution too low (>1 hour)                                     | ~55 km (TL319L60); 3-hourly  | 1958–present      | [NCAR](https://rda.ucar.edu/datasets/ds628.1/) |
| Italy               | MERIDA                 | Outdated (no update since 2024)                                                                        | 4—7 km                       | 1990 - 2024       | [MERIDA](https://merida.rse-web.it/?language=EN) |
| Global              | MERRA                  | Resolution too low (>0.25°); Outdated (no update since 2016)                                           | 0.67°×0.5° (~55 km); hourly  | 1979–2016         | [GMAO](https://gmao.gsfc.nasa.gov/reanalysis/) |
| Global              | MERRA-2                | Resolution too low (>0.25°)                                                                            | 0.625°×0.5° (~50 km); hourly | 1980–present      | [NASA GES DISC](https://disc.gsfc.nasa.gov/datasets?project=MERRA-2) |
| Global              | NCEP CFSR              | Resolution too low (>0.25°)                                                                            | ~38 km (T382); 6-hourly      | 1979–2010         | [NCEP](https://cfs.ncep.noaa.gov/cfsr), [NCAR](https://rda.ucar.edu/datasets/ds093.0/) |
| Global              | NCEP CFSv2             | Temporal resolution too low (>1 hour)                                                                  | ~28 km (T574); 6-hourly      | 2011–present      | [NOAA NCEI](https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc:C00877) |
| N. America          | NCEP NARR              | Resolution too low (>0.25°); Temporal resolution too low (>1 hour)                                     | ~32 km; 3-hourly             | 1979–present      | [NOAA PSL](https://psl.noaa.gov/data/narr/) |
| Global              | NCEP/DOE Reanalysis II | Resolution too low (>0.25°); Temporal resolution too low (>1 hour)                                     | 2.5° (~280 km); 6-hourly     | 1979–2026         | [NOAA PSL](https://psl.noaa.gov/data/gridded/data.ncep.reanalysis2.html) |
| Global              | NCEP/NCAR Reanalysis I | Resolution too low (>0.25°); Temporal resolution too low (>1 hour)                                     | 2.5° (~280 km); 6-hourly     | 1948–present      | [NOAA PSL](https://psl.noaa.gov/data/gridded/data.ncep.reanalysis.html) |
| Global              | NOAA LMRv2             | Resolution too low (>0.25°); Temporal resolution too low (>1 hour); Outdated (no update since 2000 CE) | ~2°; annual                  | 1–2000 CE         | [NCEI](https://www.ncei.noaa.gov/access/paleo-search/study/27850) |
| Global              | NOAA-CIRES 20CRv2      | Resolution too low (>0.25°); Temporal resolution too low (>1 hour); Outdated (no update since 2012)    | ~75 km; 6-hourly             | 1871–2012         | [NOAA PSL](https://psl.noaa.gov/data/20thC_Rean/) |
| Global              | NOAA-CIRES 20CRv2c     | Resolution too low (>0.25°); Temporal resolution too low (>1 hour); Outdated (no update since 2014)    | ~75 km; 6-hourly             | 1851–2014         | [NOAA PSL](https://psl.noaa.gov/data/20thC_Rean/), [NCAR](https://rda.ucar.edu/datasets/ds131.2/) |
| Global              | NOAA-CIRES-DOE 20CRv3  | Resolution too low (>0.25°); Temporal resolution too low (>1 hour); Outdated (no update since 2015)    | 1° ~75 km; 3-hourly          | 1836–2015         | [NOAA PSL](https://psl.noaa.gov/data/gridded/data.20thC_ReanV3.html), [NCAR](https://rda.ucar.edu/datasets/ds131.3/) |
| Norway              | NORA3                  | Temporal resolution too low (>1 hour); Outdated (no update since 2012)                                 | ~3 km; 3-hourly              | 1970–2021         | [MET Norway](https://data.met.no/dataset/64636e8c-c486-4496-bdda-89687e1d8f97) |
| New Zealand         | NZRA                   | NZRA is currently not publicly available in NIWA DataHub                                               | 1.5 km; 30 min               | 1990-             | [NIWA](https://niwa.co.nz/climate-and-weather/new-zealand-reanalysis-nzra-dataset) |
| Global              | OCADA                  | Temporal resolution too low (>1 hour); Outdated (no update since 2015)                                 | 1°; 6-hourly                 | 1836–2015         | [MRI-JMA](https://climate.mri-jma.go.jp/pub/archives/Ishii-et-al_OCADA/) |
