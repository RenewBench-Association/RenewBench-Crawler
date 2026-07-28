"""Shared base for per-operator coordinate-finding pipelines.

Defines BasePipeline, which owns everything identical across pipelines:
- constructor/operator-metadata resolution,
- the run_pipeline() step runner, and
- the "_step_*"/helper methods shared by all pipelines
  (load & dedupe, fuel-type mapping, fuzzy matching, fuel-type validation, finalize).

Concrete pipelines (see other modules in `pipelines`) inherit this and add their own
pipeline-specific "_step_*" methods & a STEPS list declaring the order to run them in.

This class shouldn't be instantiated directly -- its __init__ raises TypeError if you try.
"""

from pathlib import Path

import pandas as pd
from loguru import logger

from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.osm_api import query_osm_country_plants
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.mappings import COUNTRY_ISO2_MAP, OPERATOR_METADATA
from rbc.coordinates.matcher import NameMatrixMatcher
from rbc.coordinates.utils.fuel import classify_fueltype_match
from rbc.energy.entsoe.mappings import ACTIVE_ZONES_METADATA
from rbc.energy.utils import MissingDataError, load_df_from_file


class BasePipeline:
    """Shared location/coordinate finding pipeline steps for a single operator directory.

    NOTE:   Abbreviations are used to describe which "energy-generating entity" (EGE),
            or more colloquially: "power plant", is being handled. These are defined
            by the source they come from.

    - EGEs from the energy generation data sources      = EGEs to find coordinates for
        - System operators (entsoe, aemo, ...):         sysop
    - EGEs from the coordinate-finding sources:         = EGEs we have coordinates of
        - OpenStreetMap Overpass Turbo API:             osm
        - "Global Energy Monitor" files:                gem
        - power plant databases in Github packages:     ppdb
            - "powerplantmatching" (only Europe):           ppm
            - "osm-powerplants" (global):                   osmpp

    Not to be instantiated directly --- use subclasses (e.g. EntsoePipeline, DefaultPipeline).
    """

    STEPS: list[str] = []

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path | None,
        gemloc: GEMLocator | None,
        ppdb_loc: PPMLocator | OSMPPLocator | None,
        osm_update: bool = False,
        osm_live: bool = False,
    ) -> None:
        """Initialize BasePipeline class.

        Args:
            input_dir (Path): Path to the raw energy generation file (assuming CSV here).
            output_dir (Path, optional): Path to the directory where any output files may be
                saved. If None, output files are not saved.
            gemloc (GEMLocator, optional): Pre-built GEM locator to reuse. If None,
                GEM is disabled.
            ppdb_loc (PPMLocator | OSMPPLocator optional): Pre-built locator to reuse the
                European PPM CSV or global OSMPP CSV. If None, CSV-based location is disabled.
            osm_update (bool): Re-fetch OSM data from the Overpass and overwrite the local
                ``overpass_..._plants.parquet`` file even if it already exists.
                Corresponds to the ``--update`` / ``-u`` CLI flag.
            osm_live (bool): Query Overpass live on every run, ignoring and not writing
                any local file. Corresponds to the ``--live`` CLI flag.

        Raises:
            TypeError: If this class is instantiated instead of using a subclass.
        """
        if type(self) is BasePipeline:
            raise TypeError(
                "BasePipeline must be subclassed, not instantiated directly!"
            )

        self.input_dir = input_dir
        self.output_dir = output_dir
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

        self.osm_update = osm_update
        self.osm_live = osm_live
        if not self.input_dir.is_dir():
            raise ValueError(f"Input directory '{input_dir}' is not a directory!")

        self.df_osm = pd.DataFrame()
        try:
            self.operator = [p for p in self.input_dir.parts if p in OPERATOR_METADATA][
                0
            ]
            self.country = OPERATOR_METADATA[self.operator]["country"]
            self.name_col = OPERATOR_METADATA[self.operator]["entity_col"]
            self.code_col = OPERATOR_METADATA[self.operator].get("code_col")
            self.fuel_col = OPERATOR_METADATA[self.operator].get("fuel_col")
            self.fuel_mapping = OPERATOR_METADATA[self.operator].get("fuel_mapping", {})
            if self.name_col == "":
                raise MissingDataError(
                    f"No 'entity_col' name defined in OPERATOR_METADATA for "
                    f"'{[self.operator]}':\n{OPERATOR_METADATA[self.operator]}"
                )

            if self.country == "Europe":
                bz = self.input_dir.stem
                self.country = str(
                    ACTIVE_ZONES_METADATA[bz]["alias"]
                )  # incorrect for DE!

        except IndexError:
            raise ValueError(f"No country match found for '{self.input_dir}'!")

        except KeyError as e:
            raise ValueError(
                f"No country match found in Europe for '{self.input_dir}': {e}"
            )

        except MissingDataError as e:
            raise e

        # Locators are expensive to construct, so they should be pre-built and only shared.
        self.gemloc: GEMLocator | None = gemloc
        self.ppdb_loc: PPMLocator | OSMPPLocator | None = ppdb_loc

        logger.info(
            f"{type(self).__name__} initialized for: {self.operator} ({self.country})"
        )

    def run_pipeline(self) -> pd.DataFrame:
        """Run this pipeline's STEPS end-to-end.

        Threads one DataFrame through each step (`self.STEPS`, in order) in turn.

        Returns:
            pd.DataFrame: Enriched dataframe, one row per unique generation unit.
        """
        df = pd.DataFrame()
        for step_name in self.STEPS:
            df = getattr(self, step_name)(df)

            # stop if the first step didn't return a populated df with which to continue work
            if step_name == "_step_load_and_dedupe" and len(df) == 0:
                break

        return df

    # ------------------------------------------------------------------
    # CLASS PROPERTIES (shared across steps)
    # ------------------------------------------------------------------
    @property
    def sysop_name_col(self) -> str:
        """The name of the SysOp's entity column (e.g. 'Asset Name', 'Generator')."""
        return f"sysop.{self.name_col}"

    @property
    def sysop_code_col(self) -> str | None:
        """The name of the SysOp's code column, if existent (e.g. 'id_central')."""
        return f"sysop.{self.code_col}" if self.code_col else None

    @property
    def sysop_fuel_col(self) -> str | None:
        """The name of the SysOp's fuel column, if existent (e.g. 'fuel_code')."""
        return f"sysop.{self.fuel_col}" if self.fuel_col else "sysop.fuel_type"

    # ------------------------------------------------------------------
    # SHARED STEP METHODS (run by every pipeline)
    # ------------------------------------------------------------------
    def _step_load_and_dedupe(self, df: pd.DataFrame) -> pd.DataFrame:
        """INITIALIZATION STEP --- Load raw SysOp CSVs, dedupe to one row per unique EGE.

        Dedupes code_col when given (i.e. aeso, entsoe); falls back to name_col otherwise
        for SysOp sources that have no unique code (i.e. epias).

        Args:
            df (pd.DataFrame): The empty dataframe to be populated here. Unused input is
                required so that ``run_pipeline`` functions properly.

        Returns:
            df_unique (pd.DataFrame): The working dataframe (now with unique EGs)
        """
        all_dfs: list[pd.DataFrame] = []
        for input_path in sorted(self.input_dir.glob("*.csv")):
            all_dfs.append(load_df_from_file(input_path))

        if not all_dfs:
            logger.warning(f"No CSV files found in '{self.input_dir}'.")
            return pd.DataFrame()

        df_all = pd.concat(all_dfs, ignore_index=True)

        rel_cols = [
            c
            for c in [self.name_col, self.code_col, self.fuel_col]
            if c and c in df_all.columns
        ]
        dedupe_subset = [self.code_col] if self.code_col else [self.name_col]
        df_unique = (
            df_all[rel_cols]
            .drop_duplicates(subset=dedupe_subset)
            .reset_index(drop=True)
        )

        logger.info(
            f"[{self.input_dir.name}] {len(df_unique)} unique generation units found "
            f"across {len(all_dfs)} CSV(s)."
        )
        return df_unique

    def _step_map_fuel_type(self, df: pd.DataFrame) -> pd.DataFrame:
        """PREP STEP --- Rename columns with a "sysop." prefix and flesh out the fuel column.

        Args:
            df (pd.DataFrame): The working dataframe of SysOp data.

        Returns:
            df (pd.DataFrame): The updated working dataframe (now with fuel type).
        """
        # 1. rename all columns with "sysop." prefix
        df = df.rename(columns={c: f"sysop.{c}" for c in df.columns})

        # 2. create SysOp fuel column with None values if fuel column is missing/unconfigured
        if not self.fuel_col or self.sysop_fuel_col not in df.columns:
            df[self.sysop_fuel_col] = None
            return df

        # 3. apply mapping to SysOp fuel column if mapping was provided
        if self.fuel_mapping:
            df[self.sysop_fuel_col] = df[self.sysop_fuel_col].map(
                lambda x: self.fuel_mapping.get(str(x).strip()) if pd.notna(x) else None
            )
        return df

    def _step_fuzzy_match(self, df: pd.DataFrame) -> pd.DataFrame:
        """FUZZY STEP --- Unified fuzzy name matching.

        This step uses a various different sources depending on the pipeline.
        1. GEM -> used by all pipelines.
        2. Live OSM Overpass API -> used by all pipelines.
        2. Power plant database (self.ppdb_loc), defined by the pipeline:
        - "entsoe" pipeline: self.ppdb_loc = PPM (powerplantmatching) = Europe-only data
        - "default" pipeline: self.ppdb_loc = OSMPP (OSM-power plants) = Global data
        4. EIC-derived alternative names / wcode.* candidate columns, defined by the pipeline:
        - "entsoe" pipeline: populated by entsoe's own earlier `_step_entsoe_*` steps
        - "default" pipeline: NON-EXISTENT! (row.get() -> None -> only uses sysop.<name_col>)

        If a self.<...>_loc is None, that source is disabled and not used at all.

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            df (pd.DataFrame): The updated working dataframe (now with fuzzy matchings).
        """
        self._ensure_exact_match_columns(df)
        country_code = COUNTRY_ISO2_MAP.get(str(self.country).strip().lower(), None)
        self._ensure_osm_loaded(country_code)

        matcher = NameMatrixMatcher(
            country=self.country,
            country_code=country_code,
            ppdb_locator=self.ppdb_loc,
            gem_locator=self.gemloc,
            osm_df=self.df_osm if len(self.df_osm) > 0 else None,
        )
        self._add_eic_alt_names(df, matcher)

        return self._fuzzy_match_core(
            df,
            matcher,
            lambda row: [
                row.get("wcode.EicLongName"),  # entsoe alternative
                row.get("wcode.parent.EicLongName"),  # entsoe alternative
                row.get(self.sysop_name_col),
            ],
        )

    def _step_validate_fueltype(self, df: pd.DataFrame) -> pd.DataFrame:
        """VALIDATION STEP --- Fuel-type validation for all matched units (from any source).

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            df (pd.DataFrame): The updated working dataframe (with validated fuel type).
        """
        df["fuel_type_match"] = None
        df["fuel_type_match_level"] = None
        matched_mask = (
            df["ppdb.lat"].notna() | df["gem.lat"].notna() | df["osm.lat"].notna()
        )
        for idx, row in df[matched_mask].iterrows():
            matched_fueltype = None
            if pd.notna(row.get("ppdb.lat")):
                matched_fueltype = row.get("ppdb.Fueltype")
            elif pd.notna(row.get("gem.lat")):
                matched_fueltype = row.get("gem.Fueltype")
            elif pd.notna(row.get("osm.lat")):
                matched_fueltype = row.get("osm.Fueltype")

            level = classify_fueltype_match(
                row.get(self.sysop_fuel_col), matched_fueltype
            )
            df.at[idx, "fuel_type_match"] = level != "mismatch"
            df.at[idx, "fuel_type_match_level"] = level

        mismatches = (df["fuel_type_match_level"] == "mismatch").sum()
        if mismatches:
            logger.warning(
                f"[{self.input_dir.name}] Fuel-type mismatch on {mismatches} matched "
                f"unit(s) — verify these rows manually."
            )
        return df

    def _step_finalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """LAST STEP --- Finalize lat/lon, match_source, and write the output CSV.

        Args:
            df (pd.DataFrame): SysOp df with matched coordinates.

        Returns:
            df (pd.DataFrame): Enriched SysOp df with matched coordinates.
        """
        interim_lat, interim_lon = self._interim_coords(df)
        df["lat"] = interim_lat.combine_first(df["sibling.lat"])
        df["lon"] = interim_lon.combine_first(df["sibling.lon"])

        def _derived_source_row(r: pd.Series) -> str:
            if pd.notna(r.get("osm.lat")):
                return "osm"
            if pd.notna(r.get("sibling.lat")):
                return "sibling_unit"
            return "unmatched"

        derived_source = df.apply(_derived_source_row, axis=1)
        df["match_source"] = (
            df["ppdb.match_source"]
            .combine_first(df["gem.match_source"])
            .combine_first(derived_source)
        )

        total_matched = df["lat"].notna().sum()
        logger.info(
            f"[{self.input_dir.name}] Enrichment complete: {total_matched}/{len(df)} units "
            f"with coordinates. Sources: {df['match_source'].value_counts().to_dict()}"
        )

        if self.output_dir:
            out_path = Path(
                self.output_dir, f"enriched_units_{self.input_dir.name}.csv"
            )
            df.to_csv(out_path, index=False)
            logger.info(
                f"[{self.input_dir.name}] Enriched units written to '{out_path}'."
            )

        return df

    # ------------------------------------------------------------------
    # DIRECT HELPER METHODS (used by shared and/or pipeline-specific steps)
    # ------------------------------------------------------------------
    def _fuzzy_match_core(
        self,
        df: pd.DataFrame,
        matcher: NameMatrixMatcher,
        name_candidates_fn,
    ) -> pd.DataFrame:
        """FUZZY STEP HELPER --- Shared per-row fuzzy-match loop, used by every pipeline.

        The method _ensure_exact_match_columns(df) needs to have been called beforehand.

        Args:
            df (pd.DataFrame): The working dataframe.
            matcher (NameMatrixMatcher): A matcher object attuned to pipeline-related locator.
            name_candidates_fn (Callable(row)): A function to try an ordered list of name
                strings against the matcher (most authoritative first).

        Returns:
            df (pd.DataFrame): Updated working dataframe (now with ppdb, gem, osm matches).
        """
        self._ensure_exact_match_columns(df)  # defensive; no-op if already done
        matcher.build_matrix()

        for idx, row in df[self._still_unmatched(df)].iterrows():
            sysop_fuel = row.get(self.sysop_fuel_col)

            for name_candidate in name_candidates_fn(row):
                if pd.isna(name_candidate) or not str(name_candidate).strip():
                    continue

                result = matcher.match(
                    target_name=str(name_candidate).strip(),
                    fuel_type=sysop_fuel,
                    threshold=75,  # lower to get more matches with enhanced fuzzy matching
                )

                if result.matched and result.candidate:
                    candidate = result.candidate

                    if candidate.source == "ppdb":
                        df.at[idx, "ppdb.lat"] = candidate.lat
                        df.at[idx, "ppdb.lon"] = candidate.lon
                        df.at[idx, "ppdb.Name"] = candidate.name
                        df.at[idx, "ppdb.Fueltype"] = candidate.fueltype
                        df.at[idx, "ppdb.Country"] = candidate.country
                        df.at[idx, "ppdb.match_source"] = "ppdb_fuzzy_matrix"

                    elif candidate.source == "gem" and self.gemloc:
                        df.at[idx, "gem.lat"] = candidate.lat
                        df.at[idx, "gem.lon"] = candidate.lon
                        df.at[idx, "gem.plant_name"] = candidate.name
                        df.at[idx, "gem.Fueltype"] = candidate.fueltype
                        df.at[idx, "gem.Country"] = candidate.country
                        df.at[idx, "gem.match_source"] = "gem_fuzzy_matrix"

                    elif candidate.source == "osm":
                        df.at[idx, "osm.lat"] = candidate.lat
                        df.at[idx, "osm.lon"] = candidate.lon
                        df.at[idx, "osm.id"] = candidate.source_id
                        df.at[idx, "osm.type"] = None
                        df.at[idx, "osm.url"] = None
                        df.at[idx, "osm.geometry"] = None
                        df.at[idx, "osm.Fueltype"] = candidate.fueltype

                    break

        # Initialize OSM columns if they don't exist
        for col in ["lat", "lon", "id", "type", "url", "geometry"]:
            if f"osm.{col}" not in df.columns:
                df[f"osm.{col}"] = None

        ppdb_final = df["ppdb.lat"].notna().sum()
        gem_final = df["gem.lat"].notna().sum()
        osm_final = df["osm.lat"].notna().sum()
        logger.info(
            f"[{self.input_dir.name}] NameMatrixMatcher: "
            f"{ppdb_final} via ppdb (PPM/OSMPP) total, {gem_final} via GEM total, "
            f"{osm_final} via OSM."
        )
        return df

    def _sibling_fallback_core(
        self, df: pd.DataFrame, plant_group_key: pd.Series
    ) -> pd.DataFrame:
        """FALLBACK STEP HELPER --- Shared sibling-unit fallback (via prev-derived group key).

        Some units have no usable name of their own (e.g. an extra generator block added
        later) but share the same physical plant as another unit that was already matched
        by any of the previous steps. Rather than re-guessing a name for OSM/ppdb/GEM
        matching, simply inherit that sibling's coordinates.

        Args:
            df (pd.DataFrame): The working dataframe.
            plant_group_key (pd.Series): The previously-derived plant group key.

        Returns:
            df (pd.DataFrame): The updated working dataframe (now with sibling matches).
        """
        df["sibling.lat"] = None
        df["sibling.lon"] = None
        df["sibling.match_source"] = None

        interim_lat, interim_lon = self._interim_coords(df)

        has_group_key = plant_group_key.notna()
        already_matched = interim_lat.notna()

        sibling_lookup = (
            pd.DataFrame(
                {
                    "_key": plant_group_key[already_matched & has_group_key],
                    "_lat": interim_lat[already_matched & has_group_key],
                    "_lon": interim_lon[already_matched & has_group_key],
                    "_name": df.loc[
                        already_matched & has_group_key, self.sysop_name_col
                    ],
                }
            )
            .dropna(subset=["_key"])
            .drop_duplicates(subset=["_key"])
            .set_index("_key")
        )

        needs_sibling = ~already_matched & has_group_key
        for idx in df.index[needs_sibling]:
            key = plant_group_key.at[idx]
            if key in sibling_lookup.index:
                sib = sibling_lookup.loc[key]
                df.at[idx, "sibling.lat"] = sib["_lat"]
                df.at[idx, "sibling.lon"] = sib["_lon"]
                df.at[idx, "sibling.match_source"] = f"sibling_of:{sib['_name']}"

        sibling_matched_count = df["sibling.lat"].notna().sum()
        logger.info(
            f"[{self.input_dir.name}] Sibling-unit fallback: {sibling_matched_count} "
            f"additional units matched via a co-located sibling unit."
        )
        return df

    def _add_eic_alt_names(self, df: pd.DataFrame, matcher: NameMatrixMatcher) -> None:
        """Add alternative EIC names to provided matcher.

        A no-op for pipelines with no wcode.* columns (see _step_fuzzy_match).

        Args:
            df (pd.DataFrame): Df
            matcher (NameMatrixMatcher): NameMatrixMatcher instance.
        """
        for _, row in df[self._still_unmatched(df)].iterrows():
            raw_name = str(row.get(self.sysop_name_col, "") or "")
            if not raw_name:
                continue

            alt_names: list[str] = []
            for name_src in (
                "wcode.EicLongName",
                "wcode.EicDisplayName",
                "wcode.parent.EicLongName",
            ):
                n = row.get(name_src)
                if pd.notna(n) and str(n).strip() and str(n).strip() != raw_name:
                    alt_names.append(str(n).strip())

            if alt_names:
                matcher.add_alternative_names(raw_name, alt_names)

    # ------------------------------------------------------------------
    # GENERAL HELPER METHODS
    # ------------------------------------------------------------------
    @staticmethod
    def _ensure_exact_match_columns(df: pd.DataFrame) -> None:
        """Ensure ppdb.*/gem.* lat/lon/match_source columns exist (in place).

        Pipelines with an exact-ID stage (e.g. entsoe) normally create these first;
        pipelines with no exact-ID stage at all would otherwise KeyError the first
        time anything that reads these columns (_still_unmatched, _add_eic_alt_names,
        _fuzzy_match_core, _interim_coords, ...) runs. No-op once the columns
        already exist.
        """
        for col in (
            "ppdb.lat",
            "ppdb.lon",
            "ppdb.match_source",
            "gem.lat",
            "gem.lon",
            "gem.match_source",
        ):
            if col not in df.columns:
                df[col] = None

    @staticmethod
    def _still_unmatched(df: pd.DataFrame) -> pd.Series:
        """Check which rows / EGs have no  according to ppdb and GEM.

        Args:
            df (pd.DataFrame): Df to check for ppdb and GEM coordinate matches.

        Returns:
            pd.Series: Series of unmatched rows.
        """
        return df["ppdb.lat"].isna() & df["gem.lat"].isna()

    def _ensure_osm_loaded(self, country_code: str | None) -> None:
        """Ensure the OSM dataframe for the specific country code is loaded.

        Args:
            country_code (str | None): The country code, or None if no country is loaded.
        """
        if country_code and len(self.df_osm) == 0:
            self.df_osm = query_osm_country_plants(
                country_code,
                cache_dir=self.input_dir,
                force_update=self.osm_update,
                live=self.osm_live,
            )

    @staticmethod
    def _interim_coords(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Best-so-far lat/lon from exact-ID + fuzzy matches, before sibling fallback.

        Args:
            df (pd.DataFrame): DataFrame containing exact-ID + fuzzy matches.

        Returns:
            tuple[pd.Series, pd.Series]: Best-so-far lat and lon coordinates.
        """
        lat = df["ppdb.lat"].combine_first(df["gem.lat"]).combine_first(df["osm.lat"])
        lon = df["ppdb.lon"].combine_first(df["gem.lon"]).combine_first(df["osm.lon"])
        return lat, lon

    @staticmethod
    def _clean_str_series(series: pd.Series) -> pd.Series:
        """Clean up a series of strings.

        Args:
            series (pd.Series): Series of strings.

        Returns:
            pd.Series: Cleaned series.
        """
        return series.map(
            lambda v: str(v).strip() if pd.notna(v) and str(v).strip() else None
        )
