"""BARRA2.

HEALPix regridder for BARRA2 reanalysis data (regional lat-lon, R2/C2/C2_20min).
"""

import re
from pathlib import Path

import numpy as np
import xarray as xr

from rbc.weather.barra.mappings import MODEL_CONFIG, VARIABLE_TO_SHORT_PARAM
from rbc.weather.regridding.base import GridRegridder
from rbc.weather.regridding.regional import build_regional_healpix_pyramid
from rbc.weather.utils import raw_data_dir

# Reverse of barra/mappings.py's own short-code -> canonical mapping. Usable
# directly (no hand-verification needed, unlike ICON-DREAM) since BARRA2's
# short code is read from each filename and used to rename the file's one
# variable in _load_source_chunk(), matching this table's keys exactly.
_SHORT_TO_CANONICAL = {v: k for k, v in VARIABLE_TO_SHORT_PARAM.items()}

# Height-level variables get their own consolidated canonical name (a
# "height" dimension in metres), distinct from the pressure-level name for
# the same physical quantity -- otherwise pressure-level "ta" and
# height-level "ta" would collide under one canonical name. barra/mappings.py
# itself doesn't need this distinction, since it treats each height level as
# its own separate canonical variable; here they're consolidated across
# height too, matching how pressure levels are already consolidated.
_HEIGHT_BASE_TO_CANONICAL = {
    "ta": "temperature_at_height",
    "ua": "u_component_of_wind_at_height",
    "va": "v_component_of_wind_at_height",
}

# 3D (pressure-level) base codes, per barra/mappings.py's own "3D variable
# families" section.
_PRESSURE_LEVEL_BASES = ("ta", "ua", "va", "hus", "wa", "zg")

# Matches a pressure-level or height-level file's variable name: base
# letters, then digits, then an optional trailing "m" for height (metres).
_LEVEL_CODE_RE = re.compile(r"^([a-zA-Z]+)(\d+)(m?)$")


class Barra2Regridder(GridRegridder):
    """HEALPix regridder for BARRA2 reanalysis data.

    Regional lat-lon source (Australia + surrounding): no separate grid
    file, but every BARRA2 domain hits grid-doctor's regional-source
    coordinate-attachment crash (grid-doctor issue #24) -- _regrid_chunk()
    is overridden to use rbc.weather.regridding.regional's compact-cell
    workaround instead of grid_doctor.create_healpix_pyramid().

    One instance per model variant (R2/C2/C2_20min) -- each its own
    source_name/raw_dir, since they differ in native resolution and
    pressure-level sets.

    Attributes:
        model (str): BARRA2 model variant ("R2", "C2", or "C2_20min").
        temporal_res (str): This model's native temporal resolution ("1hr"
            or "20min"), looked up from barra/mappings.py's own MODEL_CONFIG.
    """

    def __init__(self, model: str, **kwargs) -> None:
        """Initializes the instance.

        Args:
            model (str): BARRA2 model variant ("R2", "C2", or "C2_20min").
            **kwargs: Forwarded to GridRegridder.__init__.
        """
        self.model = model
        self.model_config = MODEL_CONFIG[model]
        self.temporal_res = self.model_config["temporal_res"]
        super().__init__(**kwargs)
        # Computed once here (raw_dir only exists after super().__init__()),
        # rather than on every _load_source_chunk() call -- invariant for the
        # lifetime of this instance.
        self.source_dir = raw_data_dir(
            self.raw_dir,
            self.model_config["raw_folder"],
            self.model_config["temporal_res_folder"],
        )

    def _load_source_chunk(self, task: tuple) -> xr.Dataset:
        """Open, consolidate, and merge every raw BARRA2 file for one task.

        Pressure-level and height-level files each carry one variable per
        level (e.g. "..._ta950.nc" contains just "ta950") -- confirmed on
        real sample data. Both are consolidated into one stacked variable
        per base code (level/height dims respectively, per the weather Zarr
        contract's naming) before merging with single-level variables. Named
        "<base>_plev"/"<base>_height" during consolidation so
        _variable_mapping() can map pressure- and height-level variants of
        the same base code (e.g. "ta") to distinct
        canonical names, rather than colliding under one name.

        Args:
            task (tuple): (year, month) task identifier.

        Returns:
            xr.Dataset: Merged dataset for this task, in intermediate
                (disambiguated) variable names.
        """
        year, month = task
        prefix = f"barra2_{self.model}_{self.temporal_res}_{year}{month}_"
        suffix = ".nc"
        files = sorted(self.source_dir.glob(f"{prefix}*{suffix}"))

        single_level = []
        pressure_level: dict[str, list[tuple[int, xr.DataArray]]] = {}
        height_level: dict[str, list[tuple[int, xr.DataArray]]] = {}

        for f in files:
            # The short code is read from the filename (matching the wildcard
            # in the glob pattern above) and used to rename the file's one
            # variable -- BARRA2's content name always matches this already
            # (confirmed, unlike ICON-DREAM), but sourcing identity from the
            # filename consistently, rather than file contents, keeps both
            # regridders on the same pattern.
            code = f.name.removeprefix(prefix).removesuffix(suffix)
            ds = xr.open_dataset(f, chunks={})
            (var_name,) = ds.data_vars
            ds = ds.rename({str(var_name): code})
            match = _LEVEL_CODE_RE.match(code)
            if match is None:
                single_level.append(ds)
                continue
            base, level_str, is_height = match.groups()
            # A regex match alone isn't enough: some single-level variable
            # names coincidentally end in digits (e.g. "BWD03", "omega500")
            # without being real per-level files, only route to the
            # pressure/height buckets when the base code is one we actually
            # know has level variants.
            is_known_level_var = (is_height and base in _HEIGHT_BASE_TO_CANONICAL) or (
                not is_height and base in _PRESSURE_LEVEL_BASES
            )
            if not is_known_level_var:
                single_level.append(ds)
                continue
            level = int(level_str)
            target = height_level if is_height else pressure_level
            target.setdefault(base, []).append((level, ds[code]))

        # Level coordinate values are cast to float64 to match the dtype raw
        # source files themselves use for physical coordinates (confirmed
        # against real ERA5/BARRA2 data: lat/lon and ERA5's own pressure-level
        # coordinate are all float64 natively) -- these would otherwise come
        # out int64, since they're built here from plain Python ints.
        merged_vars: dict[str, xr.DataArray] = {}
        for base, level_das in pressure_level.items():
            level_das.sort(key=lambda pair: pair[0], reverse=True)
            levels, das = zip(*level_das)
            merged_vars[f"{base}_plev"] = xr.concat(
                das,
                dim=xr.DataArray(
                    np.asarray(levels, dtype=np.float64), dims="level", name="level"
                ),
            )
        for base, level_das in height_level.items():
            level_das.sort(key=lambda pair: pair[0])
            levels, das = zip(*level_das)
            merged_vars[f"{base}_height"] = xr.concat(
                das,
                dim=xr.DataArray(
                    np.asarray(levels, dtype=np.float64), dims="height", name="height"
                ),
            )

        return xr.merge([*single_level, xr.Dataset(merged_vars)], compat="no_conflicts")

    def _grid_metadata_path(self) -> Path | None:
        """BARRA2 is regional lat-lon with no separate grid definition file.

        Returns:
            None
        """
        return None

    def _regrid_chunk(self, ds: xr.Dataset, weights: Path) -> dict[int, xr.Dataset]:
        """Build the pyramid via the regional-source workaround.

        grid_doctor.create_healpix_pyramid() crashes on any regional source
        (grid-doctor issue #24, confirmed still open) -- see
        rbc.weather.regridding.regional's module docstring for the fix.

        Args:
            ds (xr.Dataset): Renamed source dataset to regrid.
            weights (Path): Path to the cached weight file from _get_weights().

        Returns:
            dict[int, xr.Dataset]: Pyramid keyed by level.
        """
        return build_regional_healpix_pyramid(
            ds, weights, max_level=self.max_level, min_level=self.min_level
        )

    def _variable_mapping(self) -> dict[str, str]:
        """Return the native-to-canonical variable name mapping for BARRA2.

        Returns:
            dict[str, str]: Mapping of BARRA2 short codes (or the
                intermediate "<base>_plev"/"<base>_height" consolidated
                names) to canonical names.
        """
        mapping = dict(_SHORT_TO_CANONICAL)
        for base, canonical in _HEIGHT_BASE_TO_CANONICAL.items():
            mapping[f"{base}_height"] = canonical
        for base in _PRESSURE_LEVEL_BASES:
            if base in _SHORT_TO_CANONICAL:
                mapping[f"{base}_plev"] = _SHORT_TO_CANONICAL[base]
        return mapping
