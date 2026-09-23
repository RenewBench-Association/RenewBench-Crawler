"""ICON-DREAM.

HEALPix regridder for ICON-DREAM NWP data (unstructured icosahedral, Global/EU).
"""

from pathlib import Path

import cfgrib  # type: ignore[import-untyped]
import xarray as xr

from rbc.weather.icon_dream.downloader import _get_model_config, _normalize_model
from rbc.weather.icon_dream.mappings import VARIABLE_TO_SHORT_PARAM
from rbc.weather.regridding.base import GridRegridder
from rbc.weather.regridding.grib import (
    flatten_forecast_dims,
    grib_quantization_step,
)
from rbc.weather.regridding.regional import build_regional_healpix_pyramid
from rbc.weather.utils import raw_data_dir

# Reverse of icon_dream/mappings.py's own short-code -> canonical mapping.
# Keyed by DWD short code: _load_source_chunk() renames each file's variable
# to the code in its filename first, since cfgrib's decoded name diverges
# from it (e.g. "T_2M" decodes as "t2m").
_SHORT_TO_CANONICAL = {v: k for k, v in VARIABLE_TO_SHORT_PARAM.items()}

# cfgrib's model-level dim names -> the contract's. ICON stores most 3D
# variables on the layers between model interfaces, but TKE on the interfaces
# themselves, giving it one level more than its siblings.
_VERTICAL_DIM_RENAMES = {
    "generalVerticalLayer": "model_level",
    "generalVertical": "model_level_half",
}


class IconDreamRegridder(GridRegridder):
    """HEALPix regridder for ICON-DREAM NWP data.

    Unstructured icosahedral source. Global uses grid-doctor's own pyramid
    path; EU is regional and hits grid-doctor issue #24, so `_regrid_chunk()`
    routes it through rbc.weather.regridding.regional instead.

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
        # Invariant for this instance; raw_dir only exists after super().

        self.model_dir = Path(self.raw_dir, self.model_config["raw_folder"])
        self.source_dir = raw_data_dir(
            self.raw_dir,
            self.model_config["raw_folder"],
            self.model_config["temporal_res_folder"],
        )

    def _load_source_chunk(self, task: tuple, variable: str) -> xr.Dataset:
        """Open and flatten the raw ICON-DREAM file for one task and variable.

        ICON-DREAM writes one variable per file, so the path is built from
        the variable's DWD code, and the file's one variable is renamed to
        that code (cfgrib's decoded name diverges from it). Every file carries
        a (time, step) forecast structure, flattened onto valid times, whose
        cycles spill past month boundaries and are trimmed off.

        Args:
            task (tuple): (year, month) task identifier.
            variable (str): Canonical variable name to load.

        Returns:
            xr.Dataset: Dataset for this task/variable, in the DWD short-code
                variable name, with the "values" dim renamed to "cell".
        """
        year, month = task
        label = self.model_config["label"]
        dwd_code = VARIABLE_TO_SHORT_PARAM[variable]
        f = Path(self.source_dir, f"{label}_{year}{month}_{dwd_code}_hourly.grb")
        self._quantization_steps[variable] = grib_quantization_step(f)

        datasets = []
        for ds in cfgrib.open_datasets(f, chunks={"time": 1}):
            ds = flatten_forecast_dims(ds)
            (var_name,) = ds.data_vars
            # Model-level files carry one of cfgrib's two vertical dims, both
            # with a coordinate, so rename() keeps dim and values in sync:
            # "generalVerticalLayer" for the N layers most variables use, and
            # "generalVertical" for the N+1 interfaces bounding them (TKE).
            renames: dict[str, str] = {str(var_name): dwd_code, "values": "cell"}
            for native, canonical in _VERTICAL_DIM_RENAMES.items():
                if native in ds.dims:
                    renames[native] = canonical
            datasets.append(ds.rename(renames))

        # One file can split into hypercubes with different time coverage,
        # so join="outer"; compat="no_conflicts" requires overlapping values
        # to agree instead of silently picking one.
        merged = xr.merge(datasets, join="outer", compat="no_conflicts")
        return self._trim_to_month(merged, year, month)

    def _discover_variables(self, task: tuple) -> list[str]:
        """Return every canonical ICON-DREAM variable actually downloaded for one task.

        Filename-only: the DWD code is read straight from each filename and
        mapped to a canonical name via `_SHORT_TO_CANONICAL` -- no files are
        opened.

        Args:
            task (tuple): (year, month) task identifier.

        Returns:
            list[str]: Canonical variable names found for this task.
        """
        year, month = task
        label = self.model_config["label"]
        prefix = f"{label}_{year}{month}_"
        suffix = "_hourly.grb"
        found = []
        for f in sorted(self.source_dir.glob(f"{prefix}*{suffix}")):
            dwd_code = f.name.removeprefix(prefix).removesuffix(suffix)
            canonical = _SHORT_TO_CANONICAL.get(dwd_code)
            if canonical:
                found.append(canonical)
        return found

    def _grid_metadata_path(self) -> Path | None:
        """Return this model's grid definition file (not the -grfinfo one).

        Returns:
            Path | None: Path to the grid definition file under raw_dir/metadata.
        """
        grid_file = next(
            f for f in self.model_config["metadata_files"] if "grfinfo" not in f
        )
        return Path(self.model_dir, "metadata", grid_file)

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
            dict[str, str]: Mapping of DWD short codes to canonical names
                (icon_dream/mappings.py's own table, reversed).
        """
        return _SHORT_TO_CANONICAL

    def encoding_for(self, variable: str) -> dict | None:
        """Store ICON-DREAM as float32, the precision its source files actually carry.

        GRIB packs per message (its own reference value and scale per
        timestep/level), so there's no file-wide scale_factor/add_offset to
        reuse the way BARRA2's NetCDF has. Confirmed on real data instead:
        the messages are 16-bit (`bitsPerValue: 16`, binary scale 2**-10) and
        cfgrib decodes them to float32 -- the float64 that would otherwise be
        written is purely an artefact of regridding, carrying no information.

        Args:
            variable (str): Canonical variable name (unused -- every
                ICON-DREAM variable comes from the same GRIB decoding path).

        Returns:
            dict | None: {"dtype": "float32"}.
        """
        return {"dtype": "float32"}
