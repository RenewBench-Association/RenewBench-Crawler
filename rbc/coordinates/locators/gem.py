"""Coordinate finding for EGEs using Global Energy Monitor (GEM) trackers.

Source: Global Energy Monitor (https://globalenergymonitor.org/download-data)

GEM publishes 8 separate xlsx "tracker" files (Coal, Oil & Gas, Wind, Solar, Hydro,
Nuclear, Bioenergy, Geothermal), each covering one fuel/technology category globally.
The newest files can be manually downloaded (registration required). If these are not
provided via ``gem_dir`` (local directory), fallback cloud-stored files from PPM's PyPSA
team are used. As of mid-2026, they use early 2025 file versions, so somewhat outdated.

Several trackers (notably Oil & Gas) already contain parsed ENTSO-E EIC codes in their
"Other IDs" columns, which gives EntsoePipeline exact matches without any fuzzy logic.
"""

from __future__ import annotations

import fnmatch
import re
from functools import cached_property
from pathlib import Path

import pandas as pd
import requests
import yaml
from loguru import logger

from rbc.coordinates.match_schema import GEM_ADAPTER, MatchCandidate
from rbc.coordinates.utils.country import normalize_locator_countries
from rbc.coordinates.utils.values import strip_str

# ------------------------------------------------------------------------
# Global parameters (mappings)
# ------------------------------------------------------------------------
# Per-XLSX map: file attributes (file name, sheet name, fuel data location) → specs for file
# "fuel_default" is EITHER a tracker's constant type OR None for a per-row "fuel" column
_TRACKER_SPECS: dict[str, dict[str, str | None]] = {
    "coal": {
        "file_name": "Global-Coal-Plant-Tracker-*.xlsx",
        "sheet": "Units",
        "fuel_default": "coal",
    },
    "oil_gas": {
        "file_name": "Global-Oil-and-Gas-Plant-Tracker-*.xlsx",
        "sheet": "Gas & Oil Units",
        "fuel_default": None,  # uses per-row 'Fuel' column
    },
    "wind": {
        "file_name": "Global-Wind-Power-Tracker-*.xlsx",
        "sheet": "Data",
        "fuel_default": "wind",
    },
    "solar": {
        "file_name": "Global-Solar-Power-Tracker-*.xlsx",
        "sheet": "Utility-Scale (1 MW+)",
        "fuel_default": "solar",
    },
    "hydro": {
        "file_name": "Global-Hydropower-Tracker-*.xlsx",
        "sheet": "Data",
        "fuel_default": "hydro",
    },
    "nuclear": {
        "file_name": "Global-Nuclear-Power-Tracker-*.xlsx",
        "sheet": "Data",
        "fuel_default": "nuclear",
    },
    "bioenergy": {
        "file_name": "Global-Bioenergy-Power-Tracker-*.xlsx",
        "sheet": "Data",
        "fuel_default": None,  # uses per-row 'Fuel' column
    },
    "geothermal": {
        "file_name": "Geothermal-Power-Tracker-*.xlsx",
        "sheet": "Data",
        "fuel_default": "thermal",
    },
}

# Per-XLSX map: column name → canonical column names.
# Only columns that differ from canonical are listed, rest as is. Handled by _first_present().
_COLUMN_ALIASES: dict[str, dict[str, list[str]]] = {
    "coal": {
        "plant_name": ["Plant name"],
        "unit_name": ["Unit name"],
        "gem_unit_id": ["GEM unit/phase ID"],
        "other_ids_unit": [],
        "other_ids_location": [],
    },
    "oil_gas": {
        "plant_name": ["Plant name"],
        "unit_name": ["Unit name"],
        "gem_unit_id": ["GEM unit ID"],
        "other_ids_unit": ["Other IDs (unit)"],
        "other_ids_location": ["Other IDs (location)"],
        "fuel": ["Fuel"],
    },
    "wind": {
        "plant_name": ["Project Name"],
        "unit_name": ["Phase Name"],
        "gem_unit_id": ["GEM phase ID"],
        "other_ids_unit": ["Other IDs (unit/phase)"],
        "other_ids_location": ["Other IDs (location)"],
    },
    "solar": {
        "plant_name": ["Project Name"],
        "unit_name": ["Phase Name"],
        "gem_unit_id": ["GEM phase ID"],
        "other_ids_unit": ["Other IDs (unit/phase)"],
        "other_ids_location": ["Other IDs (location)"],
    },
    "hydro": {
        "plant_name": ["Project Name"],
        "unit_name": [],  # no unit-level name in this tracker
        "gem_unit_id": ["GEM unit ID"],
        "other_ids_unit": [],
        "other_ids_location": [],
    },
    "nuclear": {
        "plant_name": ["Project Name"],
        "unit_name": ["Unit Name"],
        "gem_unit_id": ["GEM unit ID"],
        "other_ids_unit": [],
        "other_ids_location": [],
    },
    "bioenergy": {
        "plant_name": ["Project Name"],
        "unit_name": ["Unit Name"],
        "gem_unit_id": ["GEM phase ID"],
        "other_ids_unit": [],
        "other_ids_location": ["Other IDs (location)"],
        "fuel": ["Fuel"],
    },
    "geothermal": {
        "plant_name": ["Project Name"],
        "unit_name": ["Unit Name"],
        "gem_unit_id": ["GEM unit ID"],
        "other_ids_unit": ["Other IDs (unit/phase)"],
        "other_ids_location": ["Other IDs (location)"],
    },
}

# Fallback: Public GEM files source for fallback if manual weren't downloaded
_FALLBACK_CONFIG_URL = (
    "https://raw.githubusercontent.com/PyPSA/powerplantmatching/master/powerplantmatching/"
    "package_data/config.yaml"
)

# Global map: GEM column name → (dtype, source). If source = None: use per-tracker col alias.
_GEM_COLUMN_ALTERNATIVES: dict[str, tuple[str, list[str] | None]] = {
    "plant_name": ("str", None),
    "unit_name": ("str", None),
    "gem_unit_id": ("str", None),
    "other_ids_unit": ("str", None),  # raw "Other IDs", for ENTSO-E code extraction
    "other_ids_location": ("str", None),
    "gem_location_id": ("str", ["GEM location ID"]),
    # hydro uses "Country/Area 1"/"Area 2" → default to 1 to prevent silent row dropping
    "Country": ("str", ["Country/Area", "Country/Area 1"]),
    "other_names": ("str", ["Other Name(s)", "Other name(s)"]),  # for better matching
    "Status": ("str", ["Status"]),
    "wiki_url": ("str", ["Wiki URL"]),
    "Capacity": ("num", ["Capacity (MW)", "Unit Capacity (MW)"]),
    "lat": ("num", ["Latitude"]),
    "lon": ("num", ["Longitude"]),
}

# Pattern to extract ENTSO-E EIC codes out of GEM's "Other IDs (...)" multi-value strings
_ENTSOE_ID_PATTERN = re.compile(r"ENTSO-E:\s*([^\s,]+)")


# ------------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------------
def _first_present(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    """Return the first candidate column that exists in ``df``, else an all-NaN series.

    Args:
        df (pd.DataFrame): DataFrame to be parsed for candidate columns.
        candidates (list[str]): List of candidate columns.

    Returns:
        pd.Series: Series of the first candidate column in `df`, if one exists.
    """
    for col in candidates:
        if col in df.columns:
            return df[col]

    return pd.Series([None] * len(df), index=df.index)


def _first_present_str(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    """Like ``_first_present`` function, but transforms the result to nullable string dtype.

    Several GEM data mix numeric and string values in the same column (e.g. unit names like
    `1`, `2` alongside `"Unit 1"`), which breaks parquet serialization if not normalized.

    Args:
        df (pd.DataFrame): DataFrame to be parsed for candidate columns.
        candidates (list[str]): List of candidate columns.

    Returns:
        pd.Series: Series of the first candidate column in ``df`` as strings, if one exists.
    """
    series = _first_present(df, candidates)
    return series.astype("string")


# ------------------------------------------------------------------------
# Main class
# ------------------------------------------------------------------------
class GEMLocator:
    """Coordinate locator using Global Energy Monitor (GEM) power plant trackers.

    GEM publishes 8 xlsx tracker files that can either be manually downloaded (requires
    registration) from https://globalenergymonitor.org/download-data or downloaded from
    the PPM creators' cloud storage (they remotely stored the files). This locator
    reads all found trackers, normalizes them into a single DataFrame, and caches the
    combined result as a parquet file for fast reuse.

    Attributes:
        gem_dir (Path): Directory containing the downloaded GEM xlsx tracker files.
        cache_dir (Path | None): Directory used for the combined parquet cache.
        df (pd.DataFrame): Dataframe of combined, normalized GEM data from available trackers.
            Has the columns:
            [
                'plant_name', 'unit_name', 'other_names',
                'gem_unit_id', 'other_ids_unit', 'gem_location_id', 'other_ids_location',
                'Fueltype', 'Status', 'Capacity', 'Country', 'lat', 'lon',
                'wiki_url', 'tracker'
            ]
    """

    def __init__(
        self, gem_dir: Path | None = None, cache_dir: Path | None = None
    ) -> None:
        """Initialize GEMLocator.

        Args:
            gem_dir (Path): Directory containing the downloaded GEM tracker xlsx files.
                Defaults to None, in which case PPM's cloud-stored GEM files are the fallback.
            cache_dir (Path, optional): Directory for the combined parquet cache.
                Defaults to None, in which case `gem_dir` is used to store the parquet.
        """
        self.gem_dir = Path(gem_dir) if gem_dir else None
        self.cache_dir = Path(cache_dir) if cache_dir else self.gem_dir
        self.cache_path = (
            Path(self.cache_dir, "gem_combined.parquet") if self.cache_dir else None
        )

        self.df: pd.DataFrame = pd.DataFrame()
        self._load()
        logger.info(f"GEMLocator initialized: {len(self.df)} entries")

    # ------------------------------------------------------------------
    # Internal helpers for initialization
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """Load the combined GEM dataset, using the parquet cache when still fresh."""
        gem_xlsx_files = self._resolve_gem_xlsx_files()
        if not gem_xlsx_files:
            logger.warning(
                f"GEMLocator: No GEM tracker xlsx files found in '{self.gem_dir}' or "
                "the fallback (PPM's cloud storage). GEM matching will be unavailable."
            )
            return

        newest_xlsx_mtime = max(
            (p.stat().st_mtime for p in gem_xlsx_files.values() if isinstance(p, Path)),
            default=0,  # URL files (str) have no mtime -> existing cache always newer
        )
        if (
            self.cache_path
            and self.cache_path.is_file()
            and self.cache_path.stat().st_mtime >= newest_xlsx_mtime
        ):
            logger.info(
                f"GEMLocator: Loading combined data of {len(gem_xlsx_files)} GEM tracker "
                f"xlsx file(s) from cache '{self.cache_path}'"
            )
            self.df = pd.read_parquet(self.cache_path)
        else:
            logger.info(
                f"GEMLocator: Parsing {len(gem_xlsx_files)} GEM tracker xlsx file(s) "
                f"from '{self.gem_dir if self.gem_dir else _FALLBACK_CONFIG_URL}'..."
            )
            self.df = self._normalize_xlsx_into_df(gem_xlsx_files)

            if self.df.empty:
                logger.warning(
                    "GEMLocator: Nothing extracted from tracker xlsx file(s)!"
                )
                return

            if self.cache_dir and self.cache_path:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self.df.to_parquet(self.cache_path, index=False)
                logger.info(f"GEMLocator: Combined data stored to '{self.cache_path}'")
            else:
                logger.info(
                    "GEMLocator: Data not stored since no cache_dir was provided!"
                )

    def _resolve_gem_xlsx_files(self) -> dict[str, Path | str]:
        """Resolve one xlsx file per tracker key, either from `gem_dir` or the fallback.

        If a `gem_dir` was provided, the folder is searched for a fitting XLSX.
        On ties (multiple versions of the same tracker), the newest match is selected.
        If no XLSX is found that way, the fallback PPM config is used, from which a fitting
        URL to the cloud-stored tracker file is extracted.

        Returns:
            dict[str, Path | str]: Mapping from each GEM tracker xlsx key to its path / URL.
        """
        resolved: dict[str, Path | str] = {}
        for tracker, spec in _TRACKER_SPECS.items():
            file_name = str(spec.get("file_name"))
            matches: list = []

            if self.gem_dir:
                matches = sorted(
                    self.gem_dir.glob(file_name),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )

            if matches:
                resolved[tracker] = matches[0]
            else:
                for url in self._fallback_xlsx_urls:
                    if fnmatch.fnmatch(url, f"*{file_name}"):
                        resolved[tracker] = url
                        break

        return resolved

    @staticmethod
    def _normalize_xlsx_into_df(tracker_files: dict[str, Path | str]) -> pd.DataFrame:
        """Read & normalize every resolved tracker file into one combined DataFrame.

        Args:
            tracker_files (dict[str, Path | str]): Mapping from GEM key to its xlsx path URL.

        Returns:
            pd.DataFrame: DataFrame of loaded, normalized and combined GEM tracker xlsx files.
        """
        normalized_dfs: list[pd.DataFrame] = []

        for tracker, path in tracker_files.items():
            spec = _TRACKER_SPECS[tracker]
            aliases = _COLUMN_ALIASES[tracker]
            try:
                df_raw = pd.read_excel(path, sheet_name=str(spec["sheet"]))
            except Exception as e:
                logger.warning(f"GEMLocator: failed to read '{path}': {e}")
                continue

            df_norm = pd.DataFrame(index=df_raw.index)

            # Normalize each columns' values (find true column equivalents via mappings)
            # 1. All except "tracker" and "Fueltype"
            for col, (dtype, alt) in _GEM_COLUMN_ALTERNATIVES.items():
                candidates = alt if alt is not None else aliases.get(col, [])
                if dtype == "num":
                    df_norm[col] = pd.to_numeric(
                        _first_present(df_raw, candidates), errors="coerce"
                    )
                else:  # dtype == "str"
                    df_norm[col] = _first_present_str(df_raw, candidates)

            # 2. Specific handling of "tracker" and "Fueltype"
            df_norm["tracker"] = tracker

            # Fueltype: per-row 'fuel' column when available, else tracker default
            fuel = _first_present_str(df_raw, aliases.get("fuel", []))
            df_norm["Fueltype"] = fuel if fuel.notna().any() else spec["fuel_default"]

            normalized_dfs.append(df_norm)

        if not normalized_dfs:
            return pd.DataFrame()

        df = pd.concat(normalized_dfs, ignore_index=True)  # combine dataframes
        df = normalize_locator_countries(df)  # normalize the country values
        return df

    # ------------------------------------------------------------------
    # Cached properties (calculated once and re-used)
    # ------------------------------------------------------------------
    @cached_property
    def _fallback_xlsx_urls(self) -> list:
        """Get the potential fallback tracker URLs as a list of XLSXs in PPM's config file.

        The creators of PPM (PyPSA) stored a version of all 8 GEM trackers in their cloud
        to circumvent the forced download problem. The URLs of these XLSXs files are saved
        in the PPM package's config. This defines ALL XLSX URLs in config (including others).

        Returns:
            list: List of all XLSX URLs in the PPM config file or an empty list if none exist.
        """
        try:
            response = requests.get(
                _FALLBACK_CONFIG_URL, allow_redirects=True, timeout=60
            )
            response.raise_for_status()

            content = response.content.decode("utf-8")  # bytes to string
            config = yaml.safe_load(content)
            return [
                v2
                for k1, v1 in config.items()
                if isinstance(v1, dict)
                for k2, v2 in v1.items()
                if k2 == "url" and "xlsx" in v2
            ]

        except (requests.RequestException, yaml.YAMLError) as e:
            logger.warning(
                f"GEMLocator: failed to get fallback XLSX URLs from PPM: {e}"
            )

        return []

    @cached_property
    def _entsoe_id_index(self) -> dict[str, int]:
        """Pre-compute an ENTSO-E EIC code lookup (row-position index) once.

        Avoids full df scan which ``match_by_entsoe_id`` would otherwise need on every call.

        Returns:
            dict[str, int]: EIC code lookup dict.
        """
        index: dict[str, int] = {}

        if len(self.df) == 0:
            return index

        unit_ids = self.df.get("other_ids_unit", pd.Series(dtype=object))
        location_ids = self.df.get("other_ids_location", pd.Series(dtype=object))
        for pos, (unit_val, location_val) in enumerate(zip(unit_ids, location_ids)):
            for val in (unit_val, location_val):
                if isinstance(val, str):
                    for eic in _ENTSOE_ID_PATTERN.findall(val):
                        index.setdefault(eic, pos)

        return index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def match_by_entsoe_id(self, entsoe_id: str | None) -> MatchCandidate | None:
        """Find an EGE by its ENTSO-E EIC code and return the row as a MatchCandidate.

        Extracts ENTSO-E codes from GEM's "Other IDs (unit)" / "Other IDs (location)"
        columns via a pre-built EIC -> row-position index (see ``_entsoe_id_index``).

        Args:
            entsoe_id (str | None): ENTSO-E EIC code to search for.

        Returns:
            MatchCandidate | None: Matched row as a MatchCandidate if one was found,
                has coordinates and a name, else None.
        """
        target = strip_str(entsoe_id)
        if len(self.df) == 0 or target is None:
            return None

        pos = self._entsoe_id_index.get(target)
        if pos is None:
            return None

        row = self.df.iloc[pos]
        if pd.isna(row.get("lat")) or pd.isna(row.get("lon")):
            return None  # match found but no coordinates — not useful

        return MatchCandidate.from_row(row, adapter=GEM_ADAPTER)
