"""ICON-DREAM.

HEALPix regridder for ICON-DREAM NWP data (unstructured icosahedral, Global/EU).
"""

from pathlib import Path

import cfgrib  # type: ignore[import-untyped]
import pandas as pd
import xarray as xr

from rbc.weather.icon_dream.downloader import _get_model_config, _normalize_model
from rbc.weather.icon_dream.mappings import VARIABLE_TO_SHORT_PARAM
from rbc.weather.regridding.base import GridRegridder
from rbc.weather.regridding.regional import build_regional_healpix_pyramid

# Reverse of icon_dream/mappings.py's own short-code -> canonical mapping. Only
# entries confirmed against real sample data (T, T_2M) are included -- cfgrib's
# own variable naming diverges from DWD's short codes (like ERA5), so each
# additional entry needs the same kind of verification before being added.
_SHORT_TO_CANONICAL = {v: k for k, v in VARIABLE_TO_SHORT_PARAM.items()}
VARIABLE_MAPPING = {
    "t2m": _SHORT_TO_CANONICAL["T_2M"],
    "t": _SHORT_TO_CANONICAL["T"],
}


class IconDreamRegridder(GridRegridder):
    """HEALPix regridder for ICON-DREAM NWP data.

    Unstructured icosahedral source: Global is genuinely global coverage and
    uses grid-doctor's own pyramid path directly; EU is regional and hits the
    same regional-source crash as BARRA2 (grid-doctor issue #24), so
    _regrid_chunk() is overridden to use rbc.weather.regridding.regional's
    workaround only for that variant.

    One instance per model variant (global/eu), each its own source_name/raw_dir.

    Attributes:
        model (str): Normalized ICON-DREAM model key ("global" or "eu").
        model_config (dict): This model's configuration from icon_dream's own
            MODEL_CONFIG.
    """

    def __init__(self, model: str, **kwargs) -> None:
        """Initializes the instance.

        Args:
            model (str): ICON-DREAM model ("global"/"eu"/"europe", case-insensitive).
            **kwargs: Forwarded to GridRegridder.__init__.
        """
        self.model = _normalize_model(model)
        self.model_config = _get_model_config(self.model)
        super().__init__(**kwargs)

    def _load_source_chunk(self, task: tuple) -> xr.Dataset:
        """Open, flatten, and merge every raw ICON-DREAM file for one task.

        Every ICON-DREAM GRIB file (single- and model-level alike) carries a
        (time, step) forecast structure -- confirmed on real sample data,
        unlike ERA5 where only single-level files split this way -- so every
        opened hypercube is flattened via valid_time. Forecast cycles spill
        past calendar-month boundaries the same way ERA5's do, so the merged
        result is trimmed to the exact month.

        Args:
            task (tuple): (year, month) task identifier.

        Returns:
            xr.Dataset: Merged dataset for this task, in native variable names,
                with the "values" dim renamed to "cell".
        """
        year, month = task
        label = self.model_config["label"]
        files = sorted(self.raw_dir.glob(f"{label}_{year}{month}_*_hourly.grb"))

        datasets = []
        for f in files:
            for ds in cfgrib.open_datasets(f, chunks={}):
                if "step" in ds.dims:
                    ds = (
                        ds.stack(_flat=("time", "step"))
                        .swap_dims({"_flat": "valid_time"})
                        .drop_vars(["time", "step", "_flat"])
                        .rename({"valid_time": "time"})
                    )
                datasets.append(ds.rename_dims({"values": "cell"}))

        merged = xr.merge(datasets)
        return self._trim_to_month(merged, year, month)

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
        """Return this model's grid definition file (not the -grfinfo one).

        Returns:
            Path | None: Path to the grid definition file under raw_dir/metadata.
        """
        grid_file = next(
            f for f in self.model_config["metadata_files"] if "grfinfo" not in f
        )
        return Path(self.raw_dir, "metadata", grid_file)

    def _regrid_kwargs(self) -> dict:
        """ICON-DREAM is unstructured -- grid-doctor needs this told explicitly.

        Returns:
            dict: {"source_kind": "unstructured"}.
        """
        return {"source_kind": "unstructured"}

    def _regrid_chunk(self, ds: xr.Dataset, weights: Path) -> dict[int, xr.Dataset]:
        """Regrid via the regional workaround for EU; grid-doctor's own path for Global.

        Args:
            ds (xr.Dataset): Renamed source dataset to regrid.
            weights (Path): Path to the cached weight file from _get_weights().

        Returns:
            dict[int, xr.Dataset]: Pyramid keyed by level.
        """
        if self.model == "eu":
            return build_regional_healpix_pyramid(
                ds, weights, max_level=self.max_level, min_level=self.min_level
            )
        return super()._regrid_chunk(ds, weights)

    def _variable_mapping(self) -> dict[str, str]:
        """Return the native-to-canonical variable name mapping for ICON-DREAM.

        Returns:
            dict[str, str]: Mapping of cfgrib variable names to canonical names.
        """
        return VARIABLE_MAPPING
