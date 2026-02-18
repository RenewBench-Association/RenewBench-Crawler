"""BARRA reanalysis data downloader.

BARRA (Bureau of Meteorology Atmospheric Reanalysis for Australia) is a reanalysis
dataset produced by the Bureau of Meteorology. This module provides utilities for
downloading BARRA data in three resolutions:

- BARRA-R2: 11 km (0.11°) deterministic reanalysis
- BARRA-RE2: 22 km (0.22°) ensemble reanalysis
- BARRA-C2: 4 km (0.04°) convective-scale reanalysis

Data is provided via NCI THREDDS server and includes hourly, 3-hourly, daily, and
monthly temporal frequencies covering various meteorological variables.
"""

from rbc.weather.barra.downloader import BarraDownloader

__all__ = ["BarraDownloader"]
