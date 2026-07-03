"""Coordinate finding for energy entities using Global Energy Monitor (GEM) trackers.

Source: Global Energy Monitor (https://globalenergymonitor.org/download-data)

GEM publishes 8 separate xlsx "tracker" files (Coal, Oil & Gas, Wind, Solar, Hydro,
Nuclear, Bioenergy, Geothermal), each covering one fuel/technology category globally.
Files require manual download (registration required) so, unlike PPMLocator /
OSMPPLocator, there is no public URL to fetch them from automatically - the caller
must supply a local directory containing the downloaded xlsx files.

Several trackers (notably Oil & Gas) already contain parsed ENTSO-E EIC codes in
their "Other IDs" columns, which gives free exact matches without any fuzzy logic.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from loguru import logger
from rapidfuzz import fuzz, process

# Regex used to pull ENTSO-E EIC codes out of GEM's "Other IDs (...)" multi-value
# strings, e.g. "ENTSO-E: 43W-RTEC-2-GG1-B, Beyond Fossil Fuels: LV-3-1"
_ENTSOE_ID_PATTERN = re.compile(r"ENTSO-E:\s*([^\s,]+)")

# Per-tracker file glob pattern, main data sheet name, and default fuel type (used
# when the tracker itself doesn't carry a per-row "Fuel" column).
_TRACKER_SPECS: dict[str, dict[str, str | None]] = {
    "coal": {
        "glob": "Global-Coal-Plant-Tracker-*.xlsx",
        "sheet": "Units",
        "fuel_default": "coal",
    },
    "oil_gas": {
        "glob": "Global-Oil-and-Gas-Plant-Tracker-*.xlsx",
        "sheet": "Gas & Oil Units",
        "fuel_default": None,  # uses per-row 'Fuel' column
    },
    "wind": {
        "glob": "Global-Wind-Power-Tracker-*.xlsx",
        "sheet": "Data",
        "fuel_default": "wind",
    },
    "solar": {
        "glob": "Global-Solar-Power-Tracker-*.xlsx",
        "sheet": "Utility-Scale (1 MW+)",
        "fuel_default": "solar",
    },
    "hydro": {
        "glob": "Global-Hydropower-Tracker-*.xlsx",
        "sheet": "Data",
        "fuel_default": "hydro",
    },
    "nuclear": {
        "glob": "Global-Nuclear-Power-Tracker-*.xlsx",
        "sheet": "Data",
        "fuel_default": "nuclear",
    },
    "bioenergy": {
        "glob": "Global-Bioenergy-Power-Tracker-*.xlsx",
        "sheet": "Data",
        "fuel_default": None,  # uses per-row 'Fuel' column
    },
    "geothermal": {
        "glob": "Geothermal-Power-Tracker-*.xlsx",
        "sheet": "Data",
        "fuel_default": "thermal",
    },
}

# Per-tracker column-name mapping to canonical fields. Only columns that differ
# from the canonical name need to be listed; canonical names are used as-is when
# already present (handled by _first_present()).
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

_CACHE_FILENAME = "gem_combined.parquet"


def _first_present(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    """Return the first candidate column that exists in *df*, else an all-NaN series."""
    for col in candidates:
        if col in df.columns:
            return df[col]
    return pd.Series([None] * len(df), index=df.index)


def _first_present_str(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    """Like :func:`_first_present`, but coerces the result to nullable string dtype.

    Several GEM trackers mix numeric and string values in the same logical column
    (e.g. unit names like ``1``, ``2`` alongside ``"Unit 1"``), which breaks parquet
    serialization unless normalized to a single dtype up front.
    """
    series = _first_present(df, candidates)
    return series.astype("string")


class GEMLocator:
    """Coordinate locator using Global Energy Monitor (GEM) power plant trackers.

    GEM publishes 8 xlsx tracker files that must be manually downloaded (requires
    registration) from https://globalenergymonitor.org/download-data. This locator
    reads all trackers found in ``gem_dir``, normalizes them into a single
    DataFrame, and caches the combined result as a parquet file for fast reuse.

    Attributes:
        gem_dir (Path): Directory containing the downloaded GEM xlsx tracker files.
        cache_dir (Path | None): Directory used for the combined parquet cache.
        df_gem (pd.DataFrame): Combined, normalized GEM data across all trackers found.
    """

    # Columns included in the full-row dicts returned by match_by_entsoe_id /
    # fuzzy_match_by_name. Mirrors PPMLocator._PPM_COLS.
    _GEM_COLS: tuple[str, ...] = (
        "gem_unit_id",
        "gem_location_id",
        "plant_name",
        "unit_name",
        "Country",
        "Fueltype",
        "Capacity",
        "Status",
        "lat",
        "lon",
        "wiki_url",
        "tracker",
    )

    def __init__(self, gem_dir: Path, cache_dir: Path | None = None) -> None:
        """Initialize GEMLocator.

        Args:
            gem_dir (Path): Directory containing the downloaded GEM tracker xlsx files.
            cache_dir (Path, optional): Directory for the combined parquet cache.
                Defaults to ``gem_dir`` when not given.
        """
        self.gem_dir = Path(gem_dir)
        self.cache_dir = Path(cache_dir) if cache_dir else self.gem_dir
        self.df_gem: pd.DataFrame = pd.DataFrame()
        self._load()

    # ------------------------------------------------------------------
    # Loading & normalization
    # ------------------------------------------------------------------

    def _resolve_tracker_files(self) -> dict[str, Path]:
        """Resolve one xlsx file per tracker key, picking the newest match on ties."""
        resolved: dict[str, Path] = {}
        for tracker, spec in _TRACKER_SPECS.items():
            matches = sorted(
                self.gem_dir.glob(str(spec["glob"])),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if matches:
                resolved[tracker] = matches[0]
        return resolved

    def _load(self) -> None:
        """Load the combined GEM dataset, using the parquet cache when still fresh."""
        tracker_files = self._resolve_tracker_files()
        if not tracker_files:
            logger.warning(
                f"GEMLocator: no GEM tracker xlsx files found in '{self.gem_dir}'. "
                "GEM matching will be unavailable."
            )
            return

        cache_path = self.cache_dir / _CACHE_FILENAME
        newest_source_mtime = max(p.stat().st_mtime for p in tracker_files.values())

        if cache_path.exists() and cache_path.stat().st_mtime >= newest_source_mtime:
            logger.info(f"GEMLocator: loading combined data from cache '{cache_path}'")
            self.df_gem = pd.read_parquet(cache_path)
        else:
            logger.info(
                f"GEMLocator: parsing {len(tracker_files)} tracker file(s) "
                f"from '{self.gem_dir}'..."
            )
            self.df_gem = self._load_and_normalize(tracker_files)
            if not self.df_gem.empty and self.cache_dir:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self.df_gem.to_parquet(cache_path, index=False)
                logger.info(f"GEMLocator: cached combined data to '{cache_path}'")

        logger.info(
            f"GEMLocator initialized: {len(self.df_gem)} entries across {len(tracker_files)} tracker(s)"
        )

    def _load_and_normalize(self, tracker_files: dict[str, Path]) -> pd.DataFrame:
        """Read & normalize every resolved tracker file into one combined DataFrame."""
        normalized_dfs: list[pd.DataFrame] = []

        for tracker, path in tracker_files.items():
            spec = _TRACKER_SPECS[tracker]
            aliases = _COLUMN_ALIASES[tracker]
            try:
                df_raw = pd.read_excel(path, sheet_name=str(spec["sheet"]))
            except Exception as e:
                logger.warning(f"GEMLocator: failed to read '{path.name}': {e}")
                continue

            df_norm = pd.DataFrame(index=df_raw.index)
            df_norm["plant_name"] = _first_present_str(
                df_raw, aliases.get("plant_name", [])
            )
            df_norm["unit_name"] = _first_present_str(
                df_raw, aliases.get("unit_name", [])
            )
            df_norm["gem_unit_id"] = _first_present_str(
                df_raw, aliases.get("gem_unit_id", [])
            )
            df_norm["gem_location_id"] = _first_present_str(df_raw, ["GEM location ID"])
            df_norm["Country"] = _first_present_str(df_raw, ["Country/Area"])
            df_norm["Capacity"] = pd.to_numeric(
                _first_present(df_raw, ["Capacity (MW)", "Unit Capacity (MW)"]),
                errors="coerce",
            )
            df_norm["Status"] = _first_present_str(df_raw, ["Status"])
            df_norm["lat"] = pd.to_numeric(
                _first_present(df_raw, ["Latitude"]), errors="coerce"
            )
            df_norm["lon"] = pd.to_numeric(
                _first_present(df_raw, ["Longitude"]), errors="coerce"
            )
            df_norm["wiki_url"] = _first_present_str(df_raw, ["Wiki URL"])
            df_norm["tracker"] = tracker

            # Fuel type: per-row 'Fuel' column when available, else tracker default
            fuel_cols = aliases.get("fuel", [])
            if fuel_cols and any(c in df_raw.columns for c in fuel_cols):
                df_norm["Fueltype"] = _first_present_str(df_raw, fuel_cols)
            else:
                df_norm["Fueltype"] = spec["fuel_default"]

            # Keep raw "Other IDs" columns (used downstream to extract ENTSO-E codes)
            df_norm["_other_ids_unit"] = _first_present_str(
                df_raw, aliases.get("other_ids_unit", [])
            )
            df_norm["_other_ids_location"] = _first_present_str(
                df_raw, aliases.get("other_ids_location", [])
            )

            normalized_dfs.append(df_norm)

        if not normalized_dfs:
            return pd.DataFrame()

        return pd.concat(normalized_dfs, ignore_index=True)

    def _entsoe_ids_for_row(self, row: pd.Series) -> list[str]:
        """Extract all ENTSO-E EIC codes referenced by a combined GEM row."""
        ids: list[str] = []
        for col in ("_other_ids_unit", "_other_ids_location"):
            val = row.get(col)
            if isinstance(val, str):
                ids.extend(_ENTSOE_ID_PATTERN.findall(val))
        return ids

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def match_by_entsoe_id(self, entsoe_id: str | None) -> dict | None:
        """Find a power plant by its ENTSO-E EIC code and return the row as a dict.

        Extracts ENTSO-E codes from GEM's "Other IDs (unit)" / "Other IDs (location)"
        columns on demand (not pre-computed, since only a subset of trackers carry
        these references).

        Args:
            entsoe_id (str | None): ENTSO-E EIC code to search for.

        Returns:
            dict with keys from :attr:`_GEM_COLS`, or ``None`` if not found or the
            matched row has no coordinates.
        """
        if self.df_gem.empty or not entsoe_id or pd.isna(entsoe_id):
            return None

        target = str(entsoe_id).strip()
        mask = self.df_gem.apply(
            lambda row: target in self._entsoe_ids_for_row(row), axis=1
        )
        hits = self.df_gem[mask]
        if hits.empty:
            return None

        row = hits.iloc[0]
        if pd.isna(row.get("lat")) or pd.isna(row.get("lon")):
            return None

        return {col: (row[col] if col in row.index else None) for col in self._GEM_COLS}

    def fuzzy_match_by_name(
        self,
        name: str | None,
        country: str | None = None,
        fuel_type: str | None = None,
        threshold: int = 85,
    ) -> dict | None:
        """Fuzzy-match a plant name against the combined GEM database.

        Uses ``fuzz.WRatio``. Only rows with coordinates are considered. Filtering
        by *country* first (when given) is important to avoid cross-country name
        collisions (e.g. generically-named plants like "Riga" duplicated by unit).

        Args:
            name (str | None): Plant name to search for.
            country (str | None): Restrict candidates to this country, if given.
            fuel_type (str | None): Currently unused for filtering (reserved for a
                future guardrail); fuel-type compatibility should be validated by
                the caller using the returned ``Fueltype``.
            threshold (int): Minimum WRatio score (0-100) to accept a match.
                Defaults to 85.

        Returns:
            dict with keys from :attr:`_GEM_COLS` plus ``"gem_match_score"`` and
            ``"gem_tie_count"`` (number of other rows tied at the same top score),
            or ``None`` if no match above *threshold* was found.
        """
        if self.df_gem.empty or not name or pd.isna(name):
            return None

        df_candidates = self.df_gem.dropna(subset=["lat", "lon"])
        if country:
            df_candidates = df_candidates[
                df_candidates["Country"].astype(str).str.strip().str.lower()
                == str(country).strip().lower()
            ]
        if df_candidates.empty:
            return None

        pp_names: list[str] = df_candidates["plant_name"].dropna().tolist()
        if not pp_names:
            return None
        pp_names_lower = [n.lower() for n in pp_names]

        matches = process.extract(
            str(name).lower(), pp_names_lower, scorer=fuzz.WRatio, limit=5
        )
        if not matches or float(matches[0][1]) < threshold:
            return None

        top_score = float(matches[0][1])
        tied = [m for m in matches if float(m[1]) == top_score]
        if len(tied) > 1:
            logger.warning(
                f"GEMLocator: fuzzy name match for '{name}' has {len(tied)} tied "
                f"candidates at score {top_score:.0f} — using the first one. "
                f"Candidates: {[t[0] for t in tied]}"
            )

        matched_lower = str(matches[0][0])
        try:
            original_name = pp_names[pp_names_lower.index(matched_lower)]
        except ValueError:
            return None

        rows = df_candidates[df_candidates["plant_name"] == original_name]
        if rows.empty:
            return None

        row = rows.iloc[0]
        result = {
            col: (row[col] if col in row.index else None) for col in self._GEM_COLS
        }
        result["gem_match_score"] = top_score
        result["gem_tie_count"] = len(tied)
        return result
