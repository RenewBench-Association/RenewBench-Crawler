"""ERA5.

HEALPix regridder for ERA5 reanalysis data (global lat-lon).
"""

from pathlib import Path

import cfgrib  # type: ignore[import-untyped]
import xarray as xr

from rbc.weather.era5.mappings import MODEL_CONFIG
from rbc.weather.regridding.base import GridRegridder
from rbc.weather.regridding.grib import (
    flatten_forecast_dims,
    grib_quantization_step,
)
from rbc.weather.utils import raw_data_dir

# Native cfgrib variable name -> canonical name. cfgrib's naming differs from
# the CDS short-param codes in rbc/weather/era5/mappings.py (e.g. cfgrib gives
# "u10" where CDS gives "10u").
VARIABLE_MAPPING = {
    # Single-level, flat-time hypercube
    "sp": "surface_pressure",
    "msl": "mean_sea_level_pressure",
    "tcc": "total_cloud_cover",
    "u10": "10m_u_component_of_wind",
    "v10": "10m_v_component_of_wind",
    "t2m": "2m_temperature",
    "d2m": "2m_dewpoint_temperature",
    "u100": "100m_u_component_of_wind",
    "v100": "100m_v_component_of_wind",
    # Single-level, (time, step) forecast-structured hypercube
    "fg10": "10m_wind_gust_since_previous_post_processing",
    "ssrd": "surface_solar_radiation_downwards",
    "e": "evaporation",
    "mx2t": "maximum_2m_temperature_since_previous_post_processing",
    "mn2t": "minimum_2m_temperature_since_previous_post_processing",
    "tp": "total_precipitation",
    # Pressure-level
    "z": "geopotential",
    "t": "temperature",
    "u": "u_component_of_wind",
    "v": "v_component_of_wind",
    "q": "specific_humidity",
    "w": "vertical_velocity",
}

# cfgrib names that come from pressure-level ("_pl_") files; everything else
# in VARIABLE_MAPPING comes from single-level ("_sl_") files. Several ERA5
# variables share one file, so this picks which file to open.
_PRESSURE_LEVEL_CFGRIB_NAMES = {"z", "t", "u", "v", "q", "w"}

_CANONICAL_TO_CFGRIB = {v: k for k, v in VARIABLE_MAPPING.items()}


class Era5Regridder(GridRegridder):
    """HEALPix regridder for ERA5 reanalysis data.

    Global lat-lon source: no separate grid file. For now, single-level
    and pressure-level files are handled.
    TODO: implement and test model-level regridding (model-level
    ERA5 uses a reduced Gaussian grid, not regular lat-lon, and
    isn't part of ERA5's default variable set).
    """

    def __init__(self, **kwargs) -> None:
        """Initializes the instance.

        Args:
            **kwargs: Forwarded to GridRegridder.__init__.
        """
        super().__init__(**kwargs)
        # Computed once here (raw_dir only exists after super().__init__()),
        # rather than on every _load_source_chunk() call -- invariant for the
        # lifetime of this instance.
        self.source_dir = raw_data_dir(
            self.raw_dir,
            MODEL_CONFIG["raw_folder"],
            MODEL_CONFIG["temporal_res_folder"],
        )

    def _load_source_chunk(self, task: tuple, variable: str) -> xr.Dataset:
        """Open the raw ERA5 file for one task, selecting just one variable.

        Several ERA5 variables share one file per (year, month, level_type),
        so this opens the sl or pl file holding the requested variable and
        narrows to its cfgrib name; the file's other variables stay lazy and
        are never read. Reads happen one timestep at a time, which
        `GridRegridder._chunk_along_time()` groups up to the memory budget.

        Single-level files carry two cfgrib hypercubes: flat-time analysis
        variables, and (time, step) forecast-structured accumulated/extreme
        ones, the latter flattened onto valid times that spill past month
        boundaries and are trimmed off.

        Args:
            task (tuple): (year, month) task identifier.
            variable (str): Canonical variable name to load.

        Returns:
            xr.Dataset: Single-variable dataset for this task, in the native
                cfgrib variable name.
        """
        year, month = task
        cfgrib_name = _CANONICAL_TO_CFGRIB[variable]
        level_type = "pl" if cfgrib_name in _PRESSURE_LEVEL_CFGRIB_NAMES else "sl"
        files = sorted(self.source_dir.glob(f"era5_{year}_{month}_{level_type}_*.grib"))
        if not files:
            raise FileNotFoundError(
                f"No '{level_type}' file found for {year}-{month} in '{self.source_dir}' "
                f"(needed for '{variable}')."
            )
        f = files[0]
        self._quantization_steps[variable] = grib_quantization_step(f, cfgrib_name)

        if level_type == "pl":
            ds = self._open_pressure_level(f)
            return self._trim_to_month(ds[[cfgrib_name]], year, month)

        for hypercube in self._open_single_level(f):
            if cfgrib_name in hypercube.data_vars:
                return self._trim_to_month(hypercube[[cfgrib_name]], year, month)
        raise ValueError(
            f"'{cfgrib_name}' (canonical: '{variable}') not found in '{f}'."
        )

    def _discover_variables(self, task: tuple) -> list[str]:
        """Return every canonical ERA5 variable actually downloaded for one task.

        The sl/pl files are opened (lazily, no bulk read) to see what cfgrib
        decoded: several variables share one file, and the filenames carry
        CDS-style codes rather than cfgrib's names.

        Args:
            task (tuple): (year, month) task identifier.

        Returns:
            list[str]: Canonical variable names found for this task.
        """
        year, month = task
        found: list[str] = []
        for f in sorted(self.source_dir.glob(f"era5_{year}_{month}_pl_*.grib")):
            ds = self._open_pressure_level(f)
            found.extend(
                VARIABLE_MAPPING[v] for v in ds.data_vars if v in VARIABLE_MAPPING
            )
        for f in sorted(self.source_dir.glob(f"era5_{year}_{month}_sl_*.grib")):
            for hypercube in self._open_single_level(f):
                found.extend(
                    VARIABLE_MAPPING[v]
                    for v in hypercube.data_vars
                    if v in VARIABLE_MAPPING
                )
        return found

    def _open_pressure_level(self, path: Path) -> xr.Dataset:
        """Open a pressure-level file, renaming its level dim to match the contract.

        cfgrib names this dimension "isobaricInhPa"; the contract uses
        "level" for pressure-level variables across all sources.

        Args:
            path (Path): Path to the pressure-level .grib file.

        Returns:
            xr.Dataset: Opened dataset with "isobaricInhPa" renamed to "level".
        """
        ds = xr.open_dataset(path, engine="cfgrib", chunks={"time": 1})
        return ds.rename({"isobaricInhPa": "level"})

    def _open_single_level(self, path: Path) -> list[xr.Dataset]:
        """Open a single-level file's hypercubes, flattening any (time, step) one.

        Args:
            path (Path): Path to the single-level .grib file.

        Returns:
            list[xr.Dataset]: One or more datasets, all with a flat time dim.
        """
        opened = []
        for ds in cfgrib.open_datasets(path, chunks={"time": 1}):
            ds = flatten_forecast_dims(ds)
            opened.append(ds)
        return opened

    def _grid_metadata_path(self) -> Path | None:
        """ERA5 is global lat-lon with no separate grid definition file.

        Returns:
            None
        """
        return None

    def _variable_mapping(self) -> dict[str, str]:
        """Return the native-to-canonical variable name mapping for ERA5.

        Returns:
            dict[str, str]: Mapping of cfgrib variable names to canonical names.
        """
        return VARIABLE_MAPPING

    def encoding_for(self, variable: str) -> dict | None:
        """Store ERA5 as float32, the precision its source files carry.

        The messages are 16-bit (`bitsPerValue: 16`, binary scale 2**-9) and
        cfgrib decodes them to float32; the float64 comes from regridding.

        Args:
            variable (str): Canonical variable name (unused: every ERA5
                variable comes from the same GRIB decoding path).

        Returns:
            dict | None: {"dtype": "float32"}.
        """
        return {"dtype": "float32"}
