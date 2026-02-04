<p align="center">
<img src="logos/RenewBench-Logo.png" alt="logo" width="400"/>
</p>

# RenewBench Crawlers and Data Processing

[![](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/RenewBench-Association/RenewBench-Crawler/main.svg)](https://results.pre-commit.ci/latest/github/RenewBench-Association/RenewBench-Crawler/main)
[![](https://img.shields.io/badge/Contact-renewbench%40lists.kit.edu-orange)](renewbench@lists.kit.edu)
[![codecov](https://codecov.io/gh/RenewBench-Association/RenewBench-Crawler/graph/badge.svg?token=WPJJT4S0RA)](https://codecov.io/gh/RenewBench-Association/RenewBench-Crawler)

## What is the RenewBench Crawler Repository?

This RenewBench repository contains code to download and process all data that is part of the RenewBench
dataset. This code is available in the RenewBench Crawlers `rcb` python package, and we also include example
configuration files and scripts to run the downloads.

## Installation
We heavily recommend installing the `rcb`package in a dedicated `Python3.11+` virtual environment. You can
install ``rcp`` directly from the GitHub repository via:
```bash
pip install git+https://github.com/RenewBench-Association/RenewBench-Crawler
```
Alternatively, you can install ``rcb`` locally. To achieve this, there are two steps you need to follow:
1. Clone the RenewBench-Crawler repository:
   ```bash
   git clone https://github.com/RenewBench-Association/RenewBench-Crawler
   ```
2. Install the package from the main branch. There are multiple installation options available:
   - Install basic dependencies: ``pip install .``
   - Install an editable version with developer dependencies: ``pip install -e ."[dev]"``

## Structure
The RenewBench-Crawlers repository is structured as shown below:
```
.
├── he he he - todo: https://tree.nathanfriend.com
```

## Documentation
Coming soon :fire:

### Data sources

#### Energy

| Region      | Source   | Platform                                                                            | Docs                                                                                                                 |
|-------------|----------|-------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| Europe      | Entso-e  | [TP](https://transparency.entsoe.eu/)                                               | [API guide](https://transparencyplatform.zendesk.com/hc/en-us/sections/12783116987028-Restful-API-integration-guide) |
| Turkey      | EPIAS    | [TP](https://seffaflik.epias.com.tr/home)                                           | [Docs](https://seffaflik.epias.com.tr/electricity-service/technical/en/index.html)                                   |
| USA         | EIA      | [API browser](www.eia.gov/opendata/browser/)                                        | [API docs](https://www.eia.gov/opendata/documentation.php)                                                           |
| Canada      | IESO     |                                                                                     |                                                                                                                      |
| Chile       | CEN      |                                                                                     |                                                                                                                      |
| Australia   | AEMO     |                                                                                     |                                                                                                                      |
| New Zealand | EAT      |                                                                                     |                                                                                                                      |
| Taiwan      | Taipower | [Realtime data](https://www.taipower.com.tw/d006/loadGraph/loadGraph/genshx_e.html) | -                                                                                                                    |

#### Weather

| Region      | Source   | Platform                                                                            | Docs                                                                                                                 |
|-------------|----------|-------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| World      | ERA5  | [TP](https://apps.ecmwf.int/data-catalogues/era5/?type=an&class=ea&stream=oper&expver=1)                                               | [API guide](https://confluence.ecmwf.int/display/CKB/How+to+download+ERA5) |

## Guides

### Running scripts

To run the data crawlers, use the scripts in the `scripts` folder. For example:
```commandline
python -m scripts.energy.entsoe_download
```
Each data crawler requires an associated config in the `configs` folder, named as the
data source is, i.e. `configs/entose.yaml`. Required values can be inserted there.

The scripts are also designed as CLIs, so you can provide user arguments via flags.
It is possible to overwrite the YAML config values via commandline, for example:
```commandline
python -m scripts.energy.entsoe_download -o paths.dst_dir_raw=/my/new/path/
```
For more information, use `--help`.

### Including a new data source

To create a data crawler for a new data source, you'll need to amend and
create several files. Here is an overview of the necessary changes to
include your `<source>` for `<type> = energy | weather` data.
 You can always look at other crawlers such as `energy/entsoe` for reference.

1. **Config** ([configs/\<type\>/](configs)): -----
    [Example: _entsoe.yaml_ file](configs/energy/entsoe.yaml)

    Create a `<type>/<source>.yaml` with (at minimum)
    - a destination directory for storing data (`paths/dst_dir_raw`)
    - any potential access information required to crawl the data (`access/...`), i.e.
      API tokens or account log-in data.

2. **Config loader** ([rbc/config/schema.py](rbc/config/schema.py)): -----
   [Example: _EntsoeConfig_ class](rbc/config/schema.py#L75)

    Amend the `rbc/config/schema.py` to
    - include a `class <Source>Config` with the attributes required by the
      `.yaml`.
    - add your class to the `SCHEMA_REGISTRY` at the bottom of the file.

3. **Source folder** ([rbc/\<type\>/\<source\>](rbc)): -----
    [Example: _entsoe_ folder](rbc/energy/entsoe)

    Create a `rbc/<type>/<source>` folder containing
    - a `downloader.py` with a `class <Source>Downloader` to coordinate data crawling.

4. **Script** ([scripts/\<type\>/\<source\>_...py](scripts)): -----
    [Example: _entsoe_download.py_ file](scripts/energy/entsoe_download.py)

    Create a script for each of your source's functionalities from step 3, i.e.
    - a `<type>/<source>_download.py` to run the `downloader.py`.

5. **Tests** ([tests/](tests)):

    Add in tests for your data crawler:
    1. In the `tests/config/conftest.py`, update the dict returned by the
       `source_configs` function to include a dict version of your `<source>.yaml` with
       placeholders,

       --- [Example: _source_configs_ function](tests/config/conftest.py#L16)
    2. In the `tests/<type>/<source>` folder, create a `test_...py` with tests for
       each of the given functionalities, i.e. `test_downloader.py`.

       --- [Example: _test_downloader.py_ file](tests/energy/entsoe/test_downloader.py)

## How to contribute
Check out our [contribution guidelines](CONTRIBUTING.md) if you are interested in contributing to the RenewBench project :fire:.
Please also carefully check our [code of conduct](CODE_OF_CONDUCT.md) :blue_heart:.

## Acknowledgments
This work is funded under the Helmholtz UNLOCK Benchmarking call and supported by the
[Helmholtz AI](https://www.helmholtz.ai/) platform grant.


-----------
<div align="center">
  <a href="http://www.kit.edu/english/index.php"><img src="./logos/logo_kit.svg" height="50px" hspace="3%" vspace="25px"></a>
</div>

<div align="center">
<a href="https://www.helmholtz.ai/"><img src="./logos/logo_hai.svg" height="25px" hspace="3%" vspace="25px"></a>
</div>
