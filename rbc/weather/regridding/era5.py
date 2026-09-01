"""ERA5.

HEALPix regridder for ERA5 reanalysis data (global lat-lon).
"""

from pathlib import Path

import cfgrib  # type: ignore[import-untyped]
import pandas as pd
import xarray as xr

from rbc.weather.era5.mappings import MODEL_CONFIG
from rbc.weather.regridding.base import GridRegridder
from rbc.weather.utils import raw_data_dir

# Native cfgrib variable name -> canonical name, verified against real sample
# data and cross-referenced with rbc/weather/era5/mappings.py's own canonical
# names (cfgrib's naming differs from the CDS short-param codes there, e.g.
# cfgrib gives "u10", CDS's own short code is "10u").
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

    def _load_source_chunk(self, task: tuple) -> xr.Dataset:
        """Open and merge every single/pressure-level file for one task.

        Single-level files carry two cfgrib hypercubes: flat-time analysis
        variables, and (time, step) forecast-structured accumulated/extreme
        variables (confirmed on real sample data), the latter is flattened
        via valid_time. Forecast-cycle valid times spill past calendar-month
        boundaries, so the merged result is trimmed to the exact month;
        otherwise a few edge hours would carry NaN analysis variables in the
        store, not because of missing real-world data but as a merge
        artifact.

        Everything opens with chunks={} (dask-lazy) -- confirmed by spike
        that merging real single/pressure-level data eagerly gets OOM-killed,
        since the (time, step) flattening forces an outer-join on mismatched
        time indices across the full global grid.

        Args:
            task (tuple): (year, month) task identifier.

        Returns:
            xr.Dataset: Merged dataset for this task, in native variable names.
        """
        year, month = task
        files = sorted(self.source_dir.glob(f"era5_{year}_{month}_sl_*.grib")) + sorted(
            self.source_dir.glob(f"era5_{year}_{month}_pl_*.grib")
        )
        datasets = [
            sub_ds
            for f in files
            for sub_ds in (
                self._open_single_level(f)
                if "_sl_" in f.name
                else [self._open_pressure_level(f)]
            )
        ]
        merged = xr.merge(datasets)
        return self._trim_to_month(merged, year, month)

    def _open_pressure_level(self, path: Path) -> xr.Dataset:
        """Open a pressure-level file, renaming its level dim to match the contract.

        cfgrib names this dimension "isobaricInhPa"; the weather Zarr contract
        uses "level" uniformly for pressure-level variables across sources.

        Args:
            path (Path): Path to the pressure-level .grib file.

        Returns:
            xr.Dataset: Opened dataset with "isobaricInhPa" renamed to "level".
        """
        ds = xr.open_dataset(path, engine="cfgrib", chunks={})
        return ds.rename({"isobaricInhPa": "level"})

    def _open_single_level(self, path: Path) -> list[xr.Dataset]:
        """Open a single-level file's hypercubes, flattening any (time, step) one.

        Args:
            path (Path): Path to the single-level .grib file.

        Returns:
            list[xr.Dataset]: One or more datasets, all with a flat time dim.
        """
        opened = []
        for ds in cfgrib.open_datasets(path, chunks={}):
            if "step" in ds.dims:
                ds = (
                    ds.stack(_flat=("time", "step"))
                    .swap_dims({"_flat": "valid_time"})
                    .drop_vars(["time", "step", "_flat"])
                    .rename({"valid_time": "time"})
                )
            opened.append(ds)
        return opened

    def _trim_to_month(self, ds: xr.Dataset, year: int, month: str) -> xr.Dataset:
        """Drop timestamps outside the exact calendar month.

        Args:
            ds (xr.Dataset): Merged dataset, possibly spanning past month
                boundaries due to forecast-cycle spillover.
            year (int): Task year.
            month (str): Task month, zero-padded.

        Returns:
            xr.Dataset: Dataset trimmed to [year-month-01, end of month].
        """
        start = pd.Timestamp(year=year, month=int(month), day=1)
        end = start + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23)
        return ds.sel(time=slice(start, end))

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
