<p align="center">
<img src="docs/logos/RenewBench-Logo.png" alt="logo" width="400"/>
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
The RenewBench-Crawler repository is structured as follows:

```text
.
├── rbc/                     # Main package
│   ├── config/                 # Processing of YAML configs
│   │   ├── loader.py             # Load and validate configs
│   │   └── schema.py             # Pydantic config models and registry
│   ├── energy/                 # Energy data crawlers
│   │   ├── adme/                 # ADME (Uruguay)
│   │   ├── aemo/                 # AEMO (Australia)
│   │   ├── aeso/                 # AESO (Canada, Alberta)
│   │   ├── cen/                  # CEN (Chile)
│   │   ├── eat/                  # EA Te Mana Hiko (New Zealand)
│   │   ├── eia/                  # EIA (US)
│   │   ├── entsoe/               # ENTSO-e (EU)
│   │   ├── epias/                # EPIAS (Turkey)
│   │   ├── ieso/                 # IESO (Canada, Ontario)
│   │   ├── ons/                  # ONS (Brazil)
│   │   └── taipower/             # Taipower (Taiwan)
│   └── weather/                # Weather data crawlers
│       ├── barra/                # BARRA2 (Australia)
│       ├── era5/                 # ERA5 (Global)
│       └── icon_dream/           # ICON-DREAM (Global/Europe)
│
├── configs/                 # YAML config files
│   ├── energy/                 # Energy source configs (EIA, ENTSO-E, EPIAS, ...)
│   └── weather/                # Weather source configs (ERA5, ICON-DREAM, ...)
│
├── scripts/                 # CLI entry points
│   ├── energy/                 # Scripts for energy sources
│   └── weather/                # Scripts for weather sources
│
├── tests/                   # Test suite
│   ├── config/                 # Tests for configuration schemas & loader
│   ├── energy/                 # Tests for energy sources
│   └── weather/                # Tests for weather sources
│
├── docs/                    # Project docs
│   ├── logos/                  # Project logos
│   └── *.md                    # Markdown overviews and guides
│
├── pyproject.toml           # Project configuration
├── .pre-commit-config.yaml  # Pre-commit hooks configuration
└── README.md                # This file
```

## Documentation
For an overview of what the repository has to offer as well as getting
started, the following are available:

- [**Data sources catalogue**](docs/data_sources.md):
  Overview of all supported energy and weather data sources, including access
  requirements and links to official docs.
- [**Usage guide**](docs/guide_usage.md):
  How to run the provided scripts of this repository (command-line interface,
  config files, output locations).

## How to contribute
Check out our [contribution guidelines](CONTRIBUTING.md) if you are interested in contributing to the RenewBench project :fire:.
Please also carefully check our [code of conduct](CODE_OF_CONDUCT.md) :blue_heart:

For details on how to include a new energy or weather data source, see the
[**step-by-step guide**](docs/guide_adding_new_source.md).

## Acknowledgments
This work is funded under the Helmholtz UNLOCK Benchmarking call and supported by the
[Helmholtz AI](https://www.helmholtz.ai/) platform grant. It was performed with the
help of the Large Scale Data Facility at the Karlsruhe Institute of
Technology funded by the Ministry of Science, Research and the Arts
Baden-Württemberg and by the Federal Ministry of Education and Research.


-----------

<p align="center">
  <a href="http://www.kit.edu/english/index.php"><img src="docs/logos/logo_kit.svg" height="50px" vspace="15" hspace="20" style="vertical-align: middle;"></a><a href="https://www.helmholtz.ai/"><img src="docs/logos/logo_hai.svg" height="25px" vspace="15" hspace="20" style="vertical-align: middle;"></a><a href="https://www.helmholtz.ai/"><img src="docs/logos/logo_hereon.svg" height="45px" vspace="15" hspace="20" style="vertical-align: middle;"></a>
</p>
