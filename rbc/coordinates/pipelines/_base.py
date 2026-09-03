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

from functools import reduce
from pathlib import Path
from pprint import pformat
from typing import cast

import country_converter as coco
import pandas as pd
from loguru import logger

from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.osm_api import query_osm_country_plants
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.mappings import OPERATOR_METADATA
from rbc.coordinates.match_schema import LOCATOR_RELIABILITY, MatchCandidate
from rbc.coordinates.matcher import NameMatcher
from rbc.coordinates.utils.fuel import classify_fueltype_match
from rbc.coordinates.utils.tokenizer import NameTokenizer
from rbc.coordinates.utils.values import strip_str
from rbc.energy.entsoe.mappings import ACTIVE_ZONES_METADATA
from rbc.energy.utils import DownloadTask, MissingDataError, load_df_from_file

TRES_PATTERN = DownloadTask._TRES_PATTERN  # temporal res dir names ("1h", "15min")
DATE_PATTERN = DownloadTask._DATE_PATTERN  # data file stems ("2020-01-05")

SORTED_LOCATORS = sorted(
    LOCATOR_RELIABILITY, key=lambda loc: LOCATOR_RELIABILITY[loc], reverse=True
)
SORTED_MATCH_SOURCES = SORTED_LOCATORS + ["sibling"]


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
        gem_loc: GEMLocator | None,
        ppdb_loc: PPMLocator | OSMPPLocator | None,
        osm_update: bool = False,
        osm_live: bool = False,
    ) -> None:
        """Initialize BasePipeline class.

        Args:
            input_dir (Path): Path to the raw energy generation file (assuming CSV here).
            output_dir (Path, optional): Path to the directory where any output files may be
                saved. If None, output files are not saved.
            gem_loc (GEMLocator, optional): Pre-built GEM locator to reuse. If None,
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

        self.ALL_STEPS: list[str] = [
            "_step_load_and_dedupe",
            "_step_prepare_matching",
            *self.STEPS,
            "_step_finalize",
        ]

        self.input_dir = input_dir
        self.output_dir = output_dir
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

        # unique output-file stem (e.g. "15min_10YRO-TEL------P")
        self.output_stem = (
            f"{input_dir.parent.name}_{input_dir.name}"
            if TRES_PATTERN.match(input_dir.parent.name)
            else input_dir.name
        )

        self.osm_update = osm_update
        self.osm_live = osm_live
        if not self.input_dir.is_dir():
            raise ValueError(f"Input directory '{input_dir}' is not a directory!")

        try:
            self.operator = [p for p in self.input_dir.parts if p in OPERATOR_METADATA][
                0
            ]
            self.country = OPERATOR_METADATA[self.operator]["country"]
            self.name_col = OPERATOR_METADATA[self.operator]["entity_col"]
            entity_mapping: dict[str, str] | dict[str, dict[str, str]] = (
                OPERATOR_METADATA[self.operator].get("entity_mapping", {})
            )
            self.name_mapping: dict[str, str] | dict[str, dict[str, str]] = (
                OPERATOR_METADATA[self.operator].get("entity_mapping", {})
            )
            self.name_str_style = OPERATOR_METADATA[self.operator].get(
                "entity_str_style", "code"
            )
            self.code_col = OPERATOR_METADATA[self.operator].get("code_col")
            self.fuel_col = OPERATOR_METADATA[self.operator].get("fuel_col")
            self.fuel_mapping = OPERATOR_METADATA[self.operator].get("fuel_mapping", {})

            if self.name_col == "":
                raise MissingDataError(
                    f"No 'entity_col' name defined in OPERATOR_METADATA for "
                    f"'{[self.operator]}':\n{OPERATOR_METADATA[self.operator]}"
                )

            self.country_code: str | None = None
            if self.country == "Europe":
                bz = self.input_dir.stem
                self.country = str(ACTIVE_ZONES_METADATA[bz]["country"])
                self.country_code = str(ACTIVE_ZONES_METADATA[bz]["alpha2"])
                nested_mapping = cast(dict[str, dict[str, str]], entity_mapping)
                self.name_mapping = nested_mapping.get(self.country_code, {})
            else:
                self.country_code = coco.convert(names=self.country, to="ISO2")
                self.name_mapping = cast(dict[str, str], entity_mapping)

            if self.country_code == "not found":
                self.country_code = None
                logger.warning(
                    f"No country code found for {self.country}! OSM matching not possible."
                )

        except IndexError:
            raise ValueError(f"No country match found for '{self.input_dir}'!")

        except KeyError as e:
            raise ValueError(
                f"No country match found in Europe for '{self.input_dir}': {e}"
            )

        except MissingDataError as e:
            raise e

        # Pre-build tokenizer for later use
        self.tok: NameTokenizer = NameTokenizer(
            name_mapping={
                **self.fuel_mapping,
                **self.name_mapping,  # takes precedence (overrides same fuel_mapping keys)
            }
        )

        # Pre-build expensive-to-construct items: locators, dfs
        self.gem_loc: GEMLocator | None = gem_loc
        self.ppdb_loc: PPMLocator | OSMPPLocator | None = ppdb_loc
        self.osm_df = pd.DataFrame()  # loaded later if required as very I/O expensive!

        logger.info(
            f"{type(self).__name__} initialized for '{self.operator}' ({self.country})\n"
            f"{pformat(vars(self), indent=4, sort_dicts=False)}"
        )

        # For logging status updates:
        self.unique_targets: int = 0  # total number of unique EGEs in operator df
        self._matched_so_far: int = 0  # running count of EGEs matched so far

    def run_pipeline(self) -> pd.DataFrame:
        """Run this pipeline's ALL_STEPS end-to-end.

        Threads one DataFrame through each step (`self.STEPS`, in order) in turn.

        Returns:
            pd.DataFrame: Enriched dataframe, one row per unique generation unit.
        """
        df = pd.DataFrame()
        for step_name in self.ALL_STEPS:
            df = getattr(self, step_name)(df)

            # stop if the first step didn't return a populated df with which to continue work
            if step_name == "_step_load_and_dedupe" and len(df) == 0:
                break

        return df

    # ------------------------------------------------------------------
    # CLASS PROPERTIES AND COLUMN SCHEMA (shared across steps)
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

    @staticmethod
    def _create_match_method_columns(df: pd.DataFrame) -> None:
        """Create all columns generally required by the matching methods/algorithms.

        This method ensures the required columns lat/lon/match_source for the matching
        methods (e.g. fuzzy name via ppdb.*/gem.*/osm.*) are created to prevent KeyErrors.

        Args:
            df (pd.DataFrame): The working dataframe of SysOp (target EGE) data.
        """
        for ms in SORTED_MATCH_SOURCES:  # currently: "gem", "ppdb", "osm", "sibling"
            for col in [f"{ms}.lat", f"{ms}.lon", f"{ms}.match_source"]:
                if col not in df.columns:
                    df[col] = None

    @staticmethod
    def _matched_coords(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Best lat/lon coords from all algorithms so far (e.g. exact-ID, fuzzy, sibling).

        Args:
            df (pd.DataFrame): The working dataFrame of SysOp (target EGE) data.

        Returns:
            tuple[pd.Series, pd.Series]: Best-so-far lat and lon coordinates.
        """
        lat = reduce(
            lambda a, b: a.combine_first(b),
            (df[f"{s}.lat"] for s in SORTED_MATCH_SOURCES),
        )
        lon = reduce(
            lambda a, b: a.combine_first(b),
            (df[f"{s}.lon"] for s in SORTED_MATCH_SOURCES),
        )
        return lat, lon

    @classmethod
    def _still_unmatched(cls, df: pd.DataFrame) -> pd.Series:
        """Check which rows / target EGEs have no match from any locator yet.

        Args:
            df (pd.DataFrame): The working dataframe of SysOp (target EGE) data.

        Returns:
            pd.Series: List of bool values, True if a target EGE is still unmatched else False.
        """
        return cls._matched_coords(df)[0].isna()

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

        # define relevant columns and ensure they actually exist in the operator data
        relevant_cols = []
        for col in [self.name_col, self.code_col, self.fuel_col]:
            if not col:
                continue
            if col not in df_all.columns:
                raise MissingDataError(f"No '{col}' column in '{self.input_dir}' CSVs!")
            relevant_cols.append(col)

        dedupe_subset = [self.code_col] if self.code_col else [self.name_col]

        # Operators may report the same EGE with & without its name, so define the unique
        # winner by sorting (named before nameless) & code existence, not appearance
        if self.code_col:
            unnamed = df_all[self.name_col].isna()
            df_all = df_all.sort_values(
                by=self.name_col, key=lambda _: unnamed, kind="stable"
            )

        df_unique = (
            df_all[relevant_cols]
            .drop_duplicates(subset=dedupe_subset)
            .reset_index(drop=True)
        )

        # If unnamed EGEs in THIS temporal resolution, check if they are named in another
        if self.code_col:
            self._backfill_names_from_other_tres(df_unique)

        self.unique_targets = len(df_unique)
        unnamed = int(df_unique[self.name_col].isna().sum())
        self._log_step_result(
            "Load & dedupe",
            matched=self.unique_targets - unnamed,
            note=(
                f"across {len(all_dfs)} CSV(s)"
                + (f"; {unnamed} unnamed (unmatchable by name)" if unnamed else "")
            ),
        )
        return df_unique

    def _step_prepare_matching(self, df: pd.DataFrame) -> pd.DataFrame:
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

        # 3. apply mapping to SysOp fuel column if mapping was provided
        elif self.fuel_mapping:
            df[self.sysop_fuel_col] = df[self.sysop_fuel_col].map(
                lambda x: self.fuel_mapping.get(strip_str(x) or "")
            )

        # 4. ensure the required columns for matching algorithms are created
        self._create_match_method_columns(df)
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
        self._create_match_method_columns(df)

        # OSM Dataframe: only fetch once and only for pipelines that use this step.
        if self.country_code and self.osm_df.empty:
            self.osm_df = query_osm_country_plants(
                self.country_code,
                cache_dir=self.input_dir,
                force_update=self.osm_update,
                live=self.osm_live,
            )

        matcher = NameMatcher(
            country=self.country,
            gem_locator=self.gem_loc,
            ppdb_locator=self.ppdb_loc,
            osm_df=self.osm_df if len(self.osm_df) > 0 else None,
            tok=self.tok,
            style_policy=self.name_str_style,
        )
        self._add_alt_names(df, matcher)

        return self._fuzzy_match_core(df, matcher)

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
                matched_fueltype = row.get("ppdb.fueltype")
            elif pd.notna(row.get("gem.lat")):
                matched_fueltype = row.get("gem.fueltype")
            elif pd.notna(row.get("osm.lat")):
                matched_fueltype = row.get("osm.fueltype")

            level = classify_fueltype_match(
                row.get(self.sysop_fuel_col), matched_fueltype
            )
            df.at[idx, "fuel_type_match"] = level != "mismatch"
            df.at[idx, "fuel_type_match_level"] = level

        mismatches = (df["fuel_type_match_level"] == "mismatch").sum()
        if mismatches:
            logger.warning(
                f"[{self.output_stem}] Fuel-type mismatch on {mismatches} matched "
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
        df["lat"], df["lon"] = self._matched_coords(df)

        # get sibling from its match_source's "<loc>_sibling_of:<donor>" as "<loc>_sibling"
        sibling_source = df["sibling.match_source"].str.split("_of:").str[0]
        derived_source = sibling_source.fillna("unmatched")

        df["match_source"] = (
            df["ppdb.match_source"]
            .combine_first(df["gem.match_source"])
            .combine_first(df["osm.match_source"])
            .combine_first(derived_source)
        )

        sources = df.loc[df["lat"].notna(), "match_source"].value_counts().to_dict()
        self._log_step_result(
            "--- TOTAL ---",
            matched=int(df["lat"].notna().sum()),
            note="\n" + "\n".join(f"    {k}:\t{v}" for k, v in sources.items()),
        )

        if self.output_dir:
            out_path = Path(self.output_dir, f"coordinates_{self.output_stem}.csv")
            df.to_csv(out_path, index=False)
            logger.info(
                f"[{self.output_stem}] Coordinates dataframe saved to '{out_path}'.\n-----"
                "--------------------------------------------------------------------------"
            )

        return df

    # ------------------------------------------------------------------
    # DIRECT HELPER METHODS (used by shared and/or pipeline-specific steps)
    # ------------------------------------------------------------------
    def _backfill_names_from_other_tres(self, df: pd.DataFrame) -> None:
        """Fill in any missing EGE names from other temporal resolutions of the same data.

        Operators may omit an EGE's name entirely in one temporal resolution while naming
        it in another. Without a name, no name-based matching can occur. Example:
        - Entsoe RO 1h:     self.name_col = 'CET_MINT2_CA', self.code_col = 30WMINTMINT2---1
        - Entsoe RO 15min:  self.name_col = '', self.code_col = 30WMINTMINT2---1

        Modifies ``df`` in place, reading files only while names are still missing.
        EGEs where no names are found (via exact code matching) are left as is.

        Args:
            df (pd.DataFrame): The deduplicated working dataframe, with one row per EGE.
        """
        unnamed = df[self.name_col].isna()
        missing_codes = set(df.loc[unnamed, self.code_col].dropna())
        if not missing_codes:
            return

        found: dict[str, str] = {}
        for other_dir in self._other_tres_dirs():
            for path in sorted(other_dir.glob("*.csv")):
                if not DATE_PATTERN.match(path.stem):
                    continue

                df_other = load_df_from_file(path)
                if not {self.name_col, self.code_col}.issubset(df_other.columns):
                    continue

                named = df_other[
                    df_other[self.code_col].isin(missing_codes)
                    & df_other[self.name_col].notna()
                ][[self.code_col, self.name_col]].drop_duplicates()

                for code, name in named.itertuples(index=False):
                    if found.setdefault(code, name) != name:
                        logger.warning(
                            f"[{self.output_stem}] '{code}' named both '{found[code]}' and "
                            f"'{name}' in other temporal resolutions. Keeping the first."
                        )

                if len(found) == len(missing_codes):
                    break

            if len(found) == len(missing_codes):
                break

        if found:
            df.loc[unnamed, self.name_col] = df.loc[unnamed, self.code_col].map(found)
            self._log_step_result(
                "Load & dedupe - recovered names",
                matched=len(found),
                total=len(missing_codes),
                note=f"from other temporal resolutions: {sorted(found.values())}",
            )

    def _fuzzy_match_core(
        self,
        df: pd.DataFrame,
        matcher: NameMatcher,
    ) -> pd.DataFrame:
        """FUZZY STEP HELPER --- Shared per-row fuzzy-match loop, used by every pipeline.

        The method _ensure_exact_match_columns(df) needs to have been called beforehand.

        Each EGE is matched on its sysop_name alone. Any further names worth trying (e.g.
        ENTSO-E's EIC registry names) are registered by _add_alt_names and enter as the
        first rungs of the matcher's own variant ladder, so all names for one EGE are
        ordered and tried within a single match() call.

        Args:
            df (pd.DataFrame): The working dataframe.
            matcher (NameMatcher): A matcher object attuned to pipeline-related locator.

        Returns:
            df (pd.DataFrame): Updated working dataframe (now with ppdb, gem, osm matches).
        """
        # 1. Dataframe setup
        self._create_match_method_columns(df)  # main df column check (no-op if already)
        fuzzy_results_list = []  # list for storing fuzzy matches as a background lookup

        # 2. Fuzzy matching candidate search
        for idx, row in df[self._still_unmatched(df)].iterrows():
            sysop_fuel = row.get(self.sysop_fuel_col)
            sysop_name = strip_str(row.get(self.sysop_name_col))
            if sysop_name is None:
                continue

            result = matcher.match(target_name=sysop_name, target_fueltype=sysop_fuel)
            fuzzy_results_list.extend(
                result.to_dicts(target_idx=idx, target_fueltype=sysop_fuel)
            )

            if result.matched and result.candidate:
                candidate = result.candidate
                locator = candidate.source

                if locator in LOCATOR_RELIABILITY:
                    self._write_candidate_into_df(
                        df,
                        idx,
                        candidate,
                        match_score=result.score,
                        match_source=f"{locator}_fuzzy",
                    )

        # 3. Postprocessing
        df_fuzzy_results = pd.DataFrame(fuzzy_results_list)

        # initialize specific OSM columns if they don't exist
        for col in ["id", "type", "url", "geometry"]:
            if f"osm.{col}" not in df.columns:
                df[f"osm.{col}"] = None

        self._log_step_result("Fuzzy-matched by name", df=df)

        # 4. Storing the fuzzy matching df
        if self.output_dir and not df_fuzzy_results.empty:
            out_path = Path(self.output_dir, f"fuzzy_matches_{self.output_stem}.csv")
            df_fuzzy_results.to_csv(out_path, index=False)
            logger.info(
                f"[{self.output_stem}] Debugging dataframe saved to '{out_path}'."
            )

        return df

    def _sibling_fallback_core(
        self, df: pd.DataFrame, plant_group_keys: pd.Series
    ) -> pd.DataFrame:
        """FALLBACK STEP HELPER --- Shared sibling-unit fallback (via prev-derived group key).

        Some units have no usable name of their own (e.g. an extra generator block added
        later) but share the same physical plant as another unit that was already matched
        by any of the previous steps. Rather than re-guessing a name for OSM/ppdb/GEM
        matching, simply inherit that sibling's coordinates.

        Args:
            df (pd.DataFrame): The working dataframe.
            plant_group_keys (pd.Series): The previously-derived plant group keys.

        Returns:
            df (pd.DataFrame): The updated working dataframe (now with sibling matches).

        Raises:
            RuntimeError: If "sibling"-related columns have been populated before this step.
        """
        if df["sibling.lat"].notna().any():
            raise RuntimeError(
                "Sibling matching has not yet occurred, but columns like 'sibling.lat' are "
                "already populated with apparent matches. Something has gone wrong!"
            )

        has_group = plant_group_keys.map(
            lambda k: isinstance(k, str) and bool(k.strip())
        )

        matched_lat, matched_lon = self._matched_coords(df)
        already_matched = matched_lat.notna()

        # define which locator each donor's coordinates came from
        donor_locator = pd.Series(None, index=df.index, dtype=object)
        for locator in reversed(SORTED_LOCATORS):  # most reliable takes precedence
            donor_locator = donor_locator.mask(df[f"{locator}.lat"].notna(), locator)

        sibling_lookup = (
            pd.DataFrame(
                {
                    "_key": plant_group_keys[already_matched & has_group],
                    "_lat": matched_lat[already_matched & has_group],
                    "_lon": matched_lon[already_matched & has_group],
                    "_name": df.loc[already_matched & has_group, self.sysop_name_col],
                    "_locator": donor_locator[already_matched & has_group],
                }
            )
            .dropna(subset=["_key"])
            .drop_duplicates(subset=["_key"])
            .set_index("_key")
        )

        needs_sibling = ~already_matched & has_group
        for idx in df.index[needs_sibling]:
            key = plant_group_keys.at[idx]
            if key in sibling_lookup.index:
                sib = sibling_lookup.loc[key]
                df.at[idx, "sibling.lat"] = sib["_lat"]
                df.at[idx, "sibling.lon"] = sib["_lon"]
                df.at[idx, "sibling.match_source"] = (
                    f"{sib['_locator']}_sibling_of:{sib['_name']}"
                )

        self._log_step_result("Matched by sibling group", df=df)
        return df

    # ------------------------------------------------------------------
    # GENERAL HELPER METHODS
    # ------------------------------------------------------------------
    def _log_step_result(
        self,
        step: str,
        df: pd.DataFrame | None = None,
        matched: int | None = None,
        total: int | None = None,
        note: str | None = None,
    ) -> None:
        """Log one pipeline step's outcome in the format shared by every step.

        Two ways to call it, depending on what the step reports:
        1. provide ``df`` for a step that adds coordinate matches: all is derived from it,
        2. provide ``matched``(opt with own ``total``) for a step that reports something else
            (e.e. number of units enriched, names recovered)

        Steps report the CUMULATIVE count. Their own contribution goes in "+N".

        Args:
            step (str): Short step label (e.g. "fuzzy name match").
            df (pd.DataFrame | None): Working df (for coordinate-matching). Defaults to None.
            matched (int | None): Explicit count (for other steps). Defaults to None.
            total (int | None): What ``matched`` is measured against. Defaults to None,
                in which case the pipeline's EGE count is used (``self.unique_targets``).
            note (str | None): Free-text added information. Defaults to None.

        Raises:
            ValueError: If neither ``df`` nor ``matched`` is given or both are.
        """
        # Option 1. Derive params (matched = # matches, delta = # new, counts = # per loc)
        delta, counts = None, None
        if df is not None and matched is None:
            matched = int(self._matched_coords(df)[0].notna().sum())
            delta = matched - self._matched_so_far
            self._matched_so_far = matched

            ms_counts: dict[str, int] = {
                ms: int(df.get(f"{ms}.lat", pd.Series(dtype=float)).notna().sum())
                for ms in SORTED_MATCH_SOURCES
            }
            counts = ", ".join(f"{k} {v}" for k, v in ms_counts.items() if v)

        # Option 2. Params provided directly, nothing to derive
        elif df is None and matched is not None:
            pass

        else:
            raise ValueError(f"Logging '{step}' requires either `df` or `matched`!")

        total = self.unique_targets if total is None else total
        share = f"{matched / total * 100:>3.0f}%" if total else "  -"

        details = []
        if delta is not None:
            details.append(f"+{delta:>3}")
        if counts:
            details.append(counts)
        if note:
            details.append(note)

        logger.info(
            f"[{self.output_stem}] {step:<32}{matched:>4}/{total:<4} ({share})"
            + (f"   {' | '.join(details)}" if details else "")
        )

    def _other_tres_dirs(self) -> list[Path]:
        """Find the equivalents of the input directory for other temporal resolutions.

        Swap the tres-component of the input path for every other resolution present, e.g.:
        - self.input_dir = "entsoe/15min/10YRO-TEL------P" -> ["entsoe/1h/10YRO-TEL------P"]
        - self.input_dir = "aeso/1h" -> ["aeso/5min"]

        Returns:
            list[Path]: Existing directories of this data in other temporal resolutions or
                empty list, if no other resolutions exists.
        """
        parts = self.input_dir.parts
        tres_idx = next((i for i, p in enumerate(parts) if TRES_PATTERN.match(p)), None)
        if tres_idx is None:
            return []

        other_dirs: list[Path] = []
        for tres_dir in sorted(Path(*parts[:tres_idx]).iterdir()):
            if not tres_dir.is_dir() or tres_dir.name == parts[tres_idx]:
                continue
            if not TRES_PATTERN.match(tres_dir.name):
                continue
            candidate = Path(tres_dir, *parts[tres_idx + 1 :])
            if candidate.is_dir():
                other_dirs.append(candidate)

        return other_dirs

    @staticmethod
    def _write_candidate_into_df(
        df: pd.DataFrame,
        idx: int,
        candidate: MatchCandidate,
        match_source: str,
        match_score: float | None = None,
    ) -> None:
        """Write a matched candidate into the df with its `<source>.*` columns.

        Args:
            df (pd.DataFrame): The working dataframe.
            idx (int): Index of the candidate to write.
            candidate (MatchCandidate): The candidate to write.
            match_source (str): The match algorithm that was used to find this candidate.
            match_score (float | None): The match score of the target and candidate,
                if one exists (e.g. for fuzzy matching).
        """
        for field, value in candidate.to_dict().items():
            df.at[idx, f"{field}"] = value

        df.at[idx, f"{candidate.source}.match_score"] = match_score
        df.at[idx, f"{candidate.source}.match_source"] = match_source

    def _add_alt_names(self, df: pd.DataFrame, matcher: NameMatcher) -> None:
        """Add alternative names to matcher. Overwritable by child pipeline (i.e. entsoe).

        Args:
            df (pd.DataFrame): Dataframe with names for which alternatives will be found.
            matcher (NameMatcher): NameMatcher instance.
        """
        return None
