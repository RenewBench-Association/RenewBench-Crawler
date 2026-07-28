from pathlib import Path

import pandas as pd

from rbc.coordinates.locator_gem import GEMLocator
from rbc.coordinates.locator_ppm import PPMLocator
from rbc.coordinates.mappings import COUNTRY_ISO2_MAP
from rbc.coordinates.pipelines._base import BasePipeline
from rbc.coordinates.tokenizer import base_name_key


class DefaultPipeline(BasePipeline):
    """Default location/coordinate finding pipeline."""

    STEPS: list[str] = [
        "_step_load_and_dedupe",
        "_step_map_fuel_type",
        "_step_fuzzy_match",
        "_step_validate_fueltype",
        "_step_sibling_fallback_name",
        "_step_finalize",
    ]

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path | None = None,
        gemloc: GEMLocator | None = None,
        ppmloc: PPMLocator | None = None,
        osm_update: bool = False,
        osm_live: bool = False,
    ) -> None:
        """Initializes the child class for the default pipeline.

        Args:
            input_dir (Path): Path to the raw energy generation file (assuming CSV here).
            output_dir (Path, optional): Path to the directory where any output files may be
                saved. Defaults to None.
            gemloc (GEMLocator, optional): Pre-built GEM locator to reuse. Defaults to
                None, in which case GEM is disabled.
            ppmloc (PPMLocator, optional): Pre-built PPM locator to reuse the pan-European
                PPM CSV or global OSMPP CSV. Defaults to None, in which case a new locator
                is built.
            osm_update (bool): Re-fetch OSM data from Overpass and overwrite the local
                ``overpass_..._plants.parquet`` file even if it already exists.
                Corresponds to the ``--update`` / ``-u`` CLI flag.
            osm_live (bool): Query Overpass live on every run, ignoring and not writing
                any local file.  Corresponds to the ``--live`` CLI flag.
        """
        super().__init__(
            input_dir=input_dir,
            output_dir=output_dir,
            gemloc=gemloc,
            ppmloc=ppmloc,
            osm_update=osm_update,
            osm_live=osm_live,
        )

        # todo: uncomment when OSMPPLocator has been added
        # if self.ppmloc is None:
        #     self.ppmloc = OSMPPLocator()

    # ------------------------------------------------------------------
    # PIPELINE STEPS (for DefaultPipeline only)
    # ------------------------------------------------------------------
    def _step_sibling_fallback_name(self, df: pd.DataFrame) -> pd.DataFrame:
        """FALLBACK STEP --- Use name matching of siblings as fallback option.

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            df (pd.DataFrame): The updated working dataframe (now with sibling name matches).
        """
        return self._sibling_fallback_core(df, self._derive_plant_group_key_name(df))

    # ------------------------------------------------------------------
    # HELPER STEPS (for DefaultPipeline only)
    # ------------------------------------------------------------------
    def _derive_plant_group_key_name(self, df: pd.DataFrame) -> pd.Series:
        """Find name-based sibling-unit grouping key for SysOps with no EIC codes.

        Reduces each unit's name to its discriminative tokens via
        rbc.coordinates.tokenizer.base_name_key, so e.g. "Plant X Unit 1" and
        "Plant X Unit 2" group together. Known, accepted limitation (same
        class of risk as the EIC-based display_prefix tier): two genuinely
        different plants that reduce to the same base name will incorrectly
        group -- there is no unique per-plant ID to fall back on for sources
        without EIC/wcode data.
        """
        country_code = COUNTRY_ISO2_MAP.get(str(self.country).strip().lower(), None)

        def _key(name: object) -> str | None:
            if pd.isna(name) or not str(name).strip():
                return None
            base = base_name_key(str(name).strip(), country_code)
            return f"name_base:{base}" if base else None

        return df[self.sysop_name_col].map(_key)
