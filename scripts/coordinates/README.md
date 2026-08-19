# Finding coordinates to combine energy and meteorological data

The majority of energy operators do not provide location information on their energy
generating entities (EGEs) - meaning their units, plants, facilities etc. This poses a
considerable challenge to consolidating the energy with extremely location-dependent weather
data. A combination of various approaches has proven necessary to identify as many coordinates
as possible.

Using various [locator sources](#locator-sources) that provide such coordinate information
for EGEs, different [strategies](#strategies) have been implemented to find matches for
the operator's EGEs.

## Locator sources

| Abbr  | Name                         | Source type | Coverage | Status                       | Data type       | Access                                                                                                                                                                                                                                                                              | License                                                                                      |
|-------|------------------------------|-------------|----------|------------------------------|-----------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| OSM   | OpenStreetMaps               | Primary     | Global   | Active                       | extracted dicts | [Overpass Turbo API](https://overpass-turbo.eu/)                                                                                                                                                                                                                                    | [ODbL](https://www.openstreetmap.org/copyright)                                              |
| GEM   | Global Energy Monitor        | Secondary   | Global   | Maintained<br> 2026          | `.xlsx` files   | Manual download from [their site](https://globalenergymonitor.org/download-data)<br> (Request all 8 "Plants" datasets)                                                                                                                                                              | [CC BY 4.0](https://globalenergymonitor.org/creative-commons-license)                        |
| OSMPP | osm-powerplants              | Secondary   | Global   | Maintained<br> 2026 (v0.1.5) | `.csv` file     | [GitHub](https://github.com/open-energy-transition/osm-powerplants) repo's [current file](https://github.com/open-energy-transition/osm-powerplants/blob/main/osm_global.csv.gz)                                                                                                    | [MIT](https://github.com/open-energy-transition/osm-powerplants/blob/main/LICENSE)           |
| PPM   | powerplantmatching           | Secondary   | Europe   | Maintained<br> 2026 (v0.8.1) | `.csv` file     | [GitHub](https://github.com/PyPSA/powerplantmatching/tree/master) repo's [current file](https://github.com/PyPSA/powerplantmatching/blob/master/powerplants.csv)                                                                                                                    | [CC BY 4.0](https://github.com/PyPSA/powerplantmatching/tree/master#licence)                 |
| GPPD  | Global Power Plants Database | Secondary   | Global   | Inactive<br> 2021 (v1.3.0)   | `.csv` file     | [GitHub](https://github.com/wri/global-power-plant-database/) repo's [latest file](https://github.com/wri/global-power-plant-database/blob/master/output_database/global_power_plant_database.csv) <br> or [their site](https://datasets.wri.org/dataset/globalpowerplantdatabase)  | [CC BY 4.0](https://github.com/wri/global-power-plant-database#global-power-plant-database)  |

> [!INFO]
>
> GPPD as a 5th source is just an idea at the moment - not (yet) implemented!

These sources are partially interdependent, as the secondary databases (s. `Source type`)
build upon primary ones. Here is an overview of the secondary's main sources:

- **GEM (Global Energy Monitor)**:
  - **Primary Sources**:
    - "Public and private sources per tracker methodology" ([s. their website](https://globalenergymonitor.org/what-tracker))
      — **Status:** Maintained | **Latest Data:** 2026 | **Update frequency**: Mostly bi-annually
  - **More Infos:** [Wiki](https://www.gem.wiki/Main_Page)

- **OSMPP (osm-powerplantmatching)**
  - **Primary Sources:**
    - [OSM (OpenStreetMaps)](https://github.com/open-energy-transition/osm-powerplants#osm-power-plants)
      — **Status:** Active | **Latest:** Now | **Update frequency**: Real-time
  - **More Infos:** [GitHub](https://github.com/open-energy-transition/osm-powerplants#osm-power-plants)

- **PPM (powerplantmatching)**
  - **Primary Sources:**
    - [MASTR (Marktstammdatenregister)](https://www.marktstammdatenregister.de/MaStR)
      — **Status:** Active | **Latest:** 2026 | **Update frequency**: Real-time
  - **Secondary Sources**:
    - [BEYONDCOAL](https://beyondfossilfuels.org/database/)
      — **Status:** Maintained | **Latest:** 2026 | **Update frequency**: Every few months
    - [GEM (Global Energy Monitor)](https://globalenergymonitor.org/) (s. above)
      — **Status:** Maintained | **Latest:** 2026 | **Update frequency**: Mostly bi-annually
    - [GEO (Global Energy Observatory)](http://globalenergyobservatory.org/)
      — **Status:** Deprecated | **Latest:** 2018
    - [GPPD (Global Power Plant Database)](https://datasets.wri.org/dataset/globalpowerplantdatabase)
      — **Status:** Inactive | **Latest:** 2021
    - [JRC-SES-EESI (European Energy Storage Inventory)](https://ses.jrc.ec.europa.eu/storage-inventory)
      — **Status:** Active | **Latest:** 2026 | **Update frequency**: Near real-time
    - [JRC Hydro-power database](https://github.com/energy-modelling-toolkit/hydro-power-database/)
      — **Status:** Maintained | **Latest:** 2025 | **Update frequency**: Unknown
    - [OPSD (Open Power System Data)](https://open-power-system-data.org/)
      — **Status:** Inactive | **Latest:** 2020
  - **More Infos:** [GitHub Config](https://github.com/PyPSA/powerplantmatching/blob/master/powerplantmatching/package_data/config.yaml#L61)

- **GPPD (Global Power Plant Database)**
  - **Primary Sources:**
    - "Machine-readable national data sources" (e.g. [ANEEL (Brazil)](https://www.gov.br/aneel/en)) and "supra-national data sources" (e.g. [AUE](https://auptde.org/en/open-data))
      — **Status:** Varied  | **Latest:** Varied
    - WRI internal database (Hand-curated data collected by WRI)
      — **Status:** Unknown | **Latest:** 2021
  - **Secondary Sources**:
    - [JRC-PPDB-OPEN (Open Power Plants Database)](https://zenodo.org/records/3574566)
      — **Status:** Deprecated | **Latest:** 2019
    - [GEO (Global Energy Observatory)](https://globalenergyobservatory.org/)
      — **Status:** Deprecated | **Latest:** 2018
    - [CARMA (Carbon Monitoring for Action)](https://www.cgdev.org/topics/carbon-monitoring-action)
      — **Status:** Inactive | **Latest:** 2010
    - [Wiki-Solar](https://www.wiki-solar.org/)
      — **Status:** Deprecated (migrated to commercialised [RenewAtlas](https://www.renewatlas.com/)) | **Latest:** 2026
  - **More Infos:** [GitHub](https://github.com/wri/global-power-plant-database#combining-multiple-data-sources)

> [!INFO]
>
> Status definition meanings:
> - "Active": automatically updating
> - "Maintained": manual, periodical updates, recent GitHub commits (< 1yr)
> - "Inactive": no recent / planned updates, no recent GitHub commits
> - "Deprecated": data no longer partially / totally accessible

### Potential other sources

Overview of options:
- [openmod power plant portfolios](https://wiki.openmod-initiative.org/wiki/Power_plant_portfolios#Power_Explorer_.2F_Global_Power_Plant_Database)

#### Europe
- [JRC-PPDB-OPEN](https://zenodo.org/records/3574566)
- [Open Power Systems Data (OPSD)](https://open-power-system-data.org/)

#### The world
- [Global Power Plant Database](https://datasets.wri.org/datasets/global-power-plant-database)
- [Global Energy Observatory](https://globalenergyobservatory.org/) - Website not functioning, account creation not possible,
  last updated 2018

## Strategies

1. _ONLY FOR EUROPE (`entsoe`)_: Data enrichment

   Enrich the raw energy data metadata with EIC codes and try to find the parent facility
   (in "entsoe" terms: finding the "production unit" of a "generation unit", or e.g. the
   power plant of a given turbine).

2. _ONLY FOR EUROPE (`entsoe`)_: Matching using the EIC code

   1. Direct matching against codes in GEM and PPM (where/if present).
   2. Parent matching (if parent was found).
   3. Sibling matching: Look at the power plants that have already been matched to see if
     the power plant is related to them.

3. Fuzzy name matching with GEM, PPM (Europe)/ OSM-PP, and OSM.

   The entity names from the raw energy source files are tokenized and weighted.
   Proper names are weighted more than other tokens (such as numerals or
   [GENERIC_UNIT_TOKENS](../../rbc/coordinates/mappings.py#L120)). These tokens are then
   matched against the power plant location sources/tables in GEM, PPM, and OSM.
   The best match wins.

   Example:
   Energy entity name "KW Hamm-Uentrop Block 10" is tokenized into the following tokens:
   "KW," "Hamm," "Uentrop," "Block," and "10." Proper names, such as "Hamm" and "Uentrop," are
   weighted with one, while other tokens, such as "Block," "10," and "KW," are weighted with
   0.1.

For more details, see the modules in the [`rbc/coordinates` folder](../../rbc/coordinates),
in particular the [`orchestrator.py`](../../rbc/coordinates/orchestrator.py).

## Running coordinate finding

The developed coordinate finding can be run directly on the downloaded, raw files of an
energy source using the `coordinate_locator` script:
```bash
$ python -m scripts.coordinates.coordinate_locator -s <SOURCE>
```

Optional arguments are:

- `-i`: The input dir(s) of the raw files. Per default, the `dst_dir_raw` in the <SOURCE>'s
  YAML config will be used
- `-o`: The output directory for storing extra extracted information (for further metadata
  processing). Per default, a subfolder `coordinates` in the `dst_dir_raw` will be used.
- `--gem-dir`: The path for the manually downloaded GEM data. Per default, none is used
  and the step therefore skipped!
- `--live`: Query the overpass API On every run (without writing / reading the local
  parquet file).
- `--update`: Re-fetch OSM data from the overpass API (even if it was done for the same data
  before).

> [!WARNING]
>
> This can only be run one source at a time. The current implementation is only developed
> for ENTSOE and will only work for CSV files (not f.e. REI's JSONs)!


# Ensuring up-to-date OSM parsing

OSM data is queried for the given operator regions by specifying the area bounds of the
Overpass Turbo API request. Often, the ISO3166-1 alpha-2 country code is definitive enough
in defining this. However, in some instances (i.e. disputed territories), it may not yield
any results. In those cases the so-called OSM country relation IDs can be used instead.

These IDs describe administrative relations with `admin_level=2` and are hard-coded into
the [mappings.py](../../rbc/coordinates/mappings.py) under the global parameter
`COUNTRY_OSM_RELATION_ID_MAP`. However, these IDs may change depending on what the OSM
community decides. Therefore, a script is included to automatically update the
`COUNTRY_OSM_RELATION_ID_MAP`. It can be run whenever required via:
```bash
$ python -m scripts.coordinates.update_osm_relation_ids
```
