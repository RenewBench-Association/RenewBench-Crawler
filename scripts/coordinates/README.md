# Finding coordinates to combine energy and meterological data

The majority of energy sources do not provide location information on their generating
entities (units, plants, facilities). This poses a considerable challenge to consolidating
the energy with extremely location-dependent weather data. A combination of various
approaches has proven necessary to identify as many coordinates as possible.
Using the [sources](#sources) described below, different [strategies](#strategies) have been
implemented.

## Sources

| Abbr   | Source                | Coverage | Datatype        | Access                                                                                                                                                                           | License                                                                            |
|--------|-----------------------|----------|-----------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| GEM    | Global Energy Monitor | Global   | `.xlsx` files   | Manual download from [their site](https://globalenergymonitor.org/download-data)<br> (Request all 8 "Plants" datasets)                                                           | [CC BY 4.0](https://globalenergymonitor.org/creative-commons-license)              |
| OSM    | OpenStreetMap         | Global   | extracted dicts | [Overpass Turbo API](https://overpass-turbo.eu/)                                                                                                                                 | [ODbL](https://www.openstreetmap.org/copyright)                                    |
| osm-pp | osm-powerplants       | Global   | `.csv` file     | [GitHub](https://github.com/open-energy-transition/osm-powerplants) repo's [current file](https://github.com/open-energy-transition/osm-powerplants/blob/main/osm_global.csv.gz) | [MIT](https://github.com/open-energy-transition/osm-powerplants/blob/main/LICENSE) |
| ppm    | powerplantmatching    | Europe   | `.csv` file     | [GitHub](https://github.com/PyPSA/powerplantmatching/tree/master) repo's [current file](https://github.com/PyPSA/powerplantmatching/blob/master/powerplants.csv)                 | [CC BY 4.0](https://github.com/PyPSA/powerplantmatching/tree/master#licence)       |

### Potential other sources

Overview of options:
- [openmod power plant portfolios](https://wiki.openmod-initiative.org/wiki/Power_plant_portfolios#Power_Explorer_.2F_Global_Power_Plant_Database)

#### Europe
- [JRC-PPDB-OPEN](https://zenodo.org/records/3574566)
- [OPSD](https://open-power-system-data.org/)

#### The world
- [Global Power Plant Database](https://datasets.wri.org/datasets/global-power-plant-database)


## Strategies

1. _ONLY FOR EUROPE (`entsoe`)_: Data enrichment

   Enrich the raw energy data metadata with EIC codes and try to find the parent facility
   (in "entsoe" terms: finding the "production unit" of a "generation unit", or e.g. the
   power plant of a given turbine).

2. _ONLY FOR EUROPE (`entsoe`): Matching using the EIC code

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
- `--gem-dir`: The path the the manually downloaded GEM data. Per default, none is used
  and the step therefore skipped!
- `--live`: Query the overpass API On every run (without writing / reading the local
  parquet file).
- `--update`: Re-fetch OSM data from the overpass API (even if it was done for the same data
  before).

> [!WARNING]
>
> This can only be run one source at a time. The current implementation is only developed
> for ENTSOE and will only work for CSV files (not f.e. REI's JSONs)!
