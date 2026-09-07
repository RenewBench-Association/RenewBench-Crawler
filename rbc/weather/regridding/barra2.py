"""BARRA2.

HEALPix regridder for BARRA2 reanalysis data (regional lat-lon, R2/C2/C2_20min).
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd
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

# Extracts the averaging/extremum window from a CF "cell_methods" attribute,
# e.g. "time: mean (interval: 1 hour)" -> ("1", "hour").
_CELL_METHODS_INTERVAL_RE = re.compile(r"interval:\s*(\d+)\s*(hour|minute)s?")


def _interval_center_shift(cell_methods: str) -> pd.Timedelta | None:
    """Return the shift that moves an interval statistic's timestamp onto BARRA2's clock.

    Confirmed on real data: BARRA2 labels interval statistics (e.g.
    "time: mean (interval: 1 hour)") at the interval's center -- half an
    hour ahead of "time: point" (instantaneous) variables for the same
    nominal timestamp. The interval length is read from `cell_methods`
    itself rather than assumed, so this stays correct for any interval
    length or BARRA2 model variant.

    Args:
        cell_methods (str): The variable's own `cell_methods` attribute.

    Returns:
        pd.Timedelta | None: Negative shift to add to `time`, or None if
            `cell_methods` doesn't mark an interval statistic.
    """
    if "time: point" in cell_methods:
        return None
    match = _CELL_METHODS_INTERVAL_RE.search(cell_methods)
    if match is None:
        return None
    value, unit = match.groups()
    return -pd.Timedelta(**{f"{unit}s": int(value)}) / 2


def _packed_encoding(encoding: dict) -> dict | None:
    """Extract a reusable CF integer-packing encoding from a raw file's own encoding.

    BARRA2's own files pack physical values into scaled int32 (scale_factor
    + add_offset), which is far more compact than the float64 xarray decodes
    them into -- reusing it directly for the regridded output avoids
    reinventing packing parameters, and is safe since int32's range leaves
    enormous headroom relative to any real value shift regridding could
    introduce (confirmed on real data: representable range hundreds of
    times wider than the actual value spread).

    Args:
        encoding (dict): A decoded DataArray's own `.encoding`, as populated
            by `xr.open_dataset()`.

    Returns:
        dict | None: {"dtype", "scale_factor", "add_offset", "_FillValue"},
            or None if `encoding` isn't CF-packed this way.
    """
    if "scale_factor" not in encoding:
        return None
    return {
        "dtype": encoding["dtype"],
        "scale_factor": encoding["scale_factor"],
        "add_offset": encoding.get("add_offset", 0.0),
        "_FillValue": encoding.get("_FillValue"),
    }


def _canonical_to_native(variable: str) -> tuple[str, str]:
    """Map a canonical variable name back to its BARRA2 base short code and kind.

    Args:
        variable (str): Canonical variable name.

    Returns:
        tuple[str, str]: (base_code, kind), where kind is "single",
            "pressure", or "height".

    Raises:
        ValueError: If `variable` isn't a known BARRA2 canonical name.
    """
    for base, canonical in _HEIGHT_BASE_TO_CANONICAL.items():
        if canonical == variable:
            return base, "height"
    for code, canonical in _SHORT_TO_CANONICAL.items():
        if canonical == variable:
            return code, "pressure" if code in _PRESSURE_LEVEL_BASES else "single"
    raise ValueError(f"Unknown BARRA2 canonical variable: {variable!r}")


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
        # Populated by _load_source_chunk() as each variable's raw file(s)
        # are opened; read back by encoding_for(). One file's packing is
        # reused for every level of a consolidated pressure-/height-level
        # variable -- see _packed_encoding()'s docstring for why that's safe.
        self._native_encodings: dict[str, dict | None] = {}
        super().__init__(**kwargs)
        # Computed once here (raw_dir only exists after super().__init__()),
        # rather than on every _load_source_chunk() call -- invariant for the
        # lifetime of this instance.
        self.source_dir = raw_data_dir(
            self.raw_dir,
            self.model_config["raw_folder"],
            self.model_config["temporal_res_folder"],
        )

    def _load_source_chunk(self, task: tuple, variable: str) -> xr.Dataset:
        """Open and consolidate the raw BARRA2 file(s) for one task and variable.

        A single-level variable is one file. A pressure-/height-level
        variable is one file per level (e.g. "..._ta950.nc" contains just
        "ta950"), consolidated here into one variable with a level/height
        dimension (per the weather Zarr contract's naming). Named
        "<base>_plev"/"<base>_height" so _variable_mapping() can map
        pressure- and height-level variants of the same base code (e.g. "ta")
        to distinct canonical names.

        Interval-statistic variables (e.g. "tasmax") have their timestamps
        shifted from the interval's center onto the same on-the-hour clock
        "time: point" variables use (see `_interval_center_shift()`), so
        every BARRA2 variable shares one "time" axis in the output store.

        Args:
            task (tuple): (year, month) task identifier.
            variable (str): Canonical variable name to load.

        Returns:
            xr.Dataset: Single-variable dataset, in intermediate
                (disambiguated) variable name.
        """
        year, month = task
        base, kind = _canonical_to_native(variable)
        prefix = f"barra2_{self.model}_{self.temporal_res}_{year}{month}_"
        suffix = ".nc"

        if kind == "single":
            f = Path(self.source_dir, f"{prefix}{base}{suffix}")
            ds = xr.open_dataset(f, chunks={})[[base]]
            self._native_encodings[variable] = _packed_encoding(ds[base].encoding)
            shift = _interval_center_shift(ds[base].attrs.get("cell_methods", ""))
            ds = ds.drop_vars(set(ds.coords) - {"time", "lat", "lon"})
            if shift is not None:
                ds = ds.assign_coords(time=ds["time"] + shift)
            return ds

        # Pressure-/height-level: one file per level, and the level set
        # itself isn't known ahead of time, so glob by base then filter with
        # an anchored regex -- e.g. base "ta" must not also match "tas", a
        # different, single-level variable that happens to start the same way.
        level_coord = "height" if kind == "height" else "pressure"
        code_pattern = (
            re.compile(rf"^{re.escape(base)}(\d+)m$")
            if kind == "height"
            else re.compile(rf"^{re.escape(base)}(\d+)$")
        )
        level_das: list[tuple[float, xr.DataArray]] = []
        for f in sorted(self.source_dir.glob(f"{prefix}{base}*{suffix}")):
            code = f.name.removeprefix(prefix).removesuffix(suffix)
            if not code_pattern.match(code):
                continue
            ds = xr.open_dataset(f, chunks={})[[code]]
            # The level value comes from the file's own scalar
            # "pressure"/"height" coordinate, not the filename -- confirmed
            # on real data the two always agree, but the file's own value is
            # the authoritative one, and using it needs no caveat in STAC
            # metadata (a filename-inferred value would). That coordinate is
            # then dropped: kept as a loose scalar rather than consolidated
            # into this method's own level/height dimension, it would
            # conflict once different variables have different level
            # coverage (confirmed on real data: "ta" has levels [1000, 950]
            # but "ua" only has [1000], so a shared "pressure" coordinate
            # named the same across both raises a MergeError).
            level = float(ds[level_coord].item())
            if variable not in self._native_encodings:
                # scale_factor is identical across a variable's level files
                # (confirmed on real data); add_offset differs per level,
                # but any one file's is safe to reuse for the whole
                # consolidated variable -- see _packed_encoding()'s
                # docstring. Only the first level file's is kept.
                self._native_encodings[variable] = _packed_encoding(ds[code].encoding)
            shift = _interval_center_shift(ds[code].attrs.get("cell_methods", ""))
            ds = ds.drop_vars(set(ds.coords) - {"time", "lat", "lon"})
            if shift is not None:
                ds = ds.assign_coords(time=ds["time"] + shift)
            level_das.append((level, ds[code]))

        # Level coordinate values are cast to float64 to match the dtype raw
        # source files themselves use for physical coordinates (confirmed
        # against real ERA5/BARRA2 data: lat/lon and ERA5's own pressure-level
        # coordinate are all float64 natively) -- these would otherwise come
        # out int64, since they're built here from plain Python floats/ints.
        level_das.sort(key=lambda pair: pair[0], reverse=(kind == "pressure"))
        levels, das = zip(*level_das)
        dim_name = "level" if kind == "pressure" else "height"
        stacked = xr.concat(
            das,
            dim=xr.DataArray(
                np.asarray(levels, dtype=np.float64), dims=dim_name, name=dim_name
            ),
        )
        native_name = f"{base}_{'plev' if kind == 'pressure' else 'height'}"
        return xr.Dataset({native_name: stacked})

    def _discover_variables(self, task: tuple) -> list[str]:
        """Return every canonical BARRA2 variable actually downloaded for one task.

        Filename-only: classifies each file's code the same way
        `_load_source_chunk()` does, then maps to a canonical name via
        `_variable_mapping()` -- no files are opened.

        Args:
            task (tuple): (year, month) task identifier.

        Returns:
            list[str]: Canonical variable names found for this task.
        """
        year, month = task
        prefix = f"barra2_{self.model}_{self.temporal_res}_{year}{month}_"
        suffix = ".nc"
        mapping = self._variable_mapping()
        found: set[str] = set()
        for f in sorted(self.source_dir.glob(f"{prefix}*{suffix}")):
            code = f.name.removeprefix(prefix).removesuffix(suffix)
            match = _LEVEL_CODE_RE.match(code)
            if match is None:
                native_key = code
            else:
                base, _, is_height = match.groups()
                is_known_level_var = (
                    is_height and base in _HEIGHT_BASE_TO_CANONICAL
                ) or (not is_height and base in _PRESSURE_LEVEL_BASES)
                native_key = (
                    f"{base}_{'height' if is_height else 'plev'}"
                    if is_known_level_var
                    else code
                )
            canonical = mapping.get(native_key)
            if canonical:
                found.add(canonical)
        return sorted(found)

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

    def encoding_for(self, variable: str) -> dict | None:
        """Return the raw file's own packed-int encoding, captured while loading.

        Args:
            variable (str): Canonical variable name.

        Returns:
            dict | None: Captured by `_load_source_chunk()`; None if that
                hasn't run yet for this variable, or the source wasn't
                CF-packed.
        """
        return self._native_encodings.get(variable)
