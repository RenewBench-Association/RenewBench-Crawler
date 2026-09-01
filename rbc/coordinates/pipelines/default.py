"""Default location/coordinate finding pipeline."""

from pathlib import Path

import pandas as pd

from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.pipelines._base import BasePipeline
from rbc.coordinates.utils.values import strip_str


class DefaultPipeline(BasePipeline):
    """Default location/coordinate finding pipeline."""

    STEPS: list[str] = [
        "_step_fuzzy_match",
        "_step_validate_fueltype",
        "_step_sibling_fallback_name",
    ]

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path | None = None,
        gem_loc: GEMLocator | None = None,
        osmpp_loc: OSMPPLocator | None = None,
        osm_update: bool = False,
        osm_live: bool = False,
    ) -> None:
        """Initializes the child class for the default pipeline.

        Args:
            input_dir (Path): Path to the raw energy generation file (assuming CSV here).
            output_dir (Path, optional): Path to the directory where any output files may be
                saved. Defaults to None.
            gem_loc (GEMLocator, optional): Pre-built GEM locator to reuse. Defaults to
                None, in which case GEM is disabled.
            osmpp_loc (OSMPPLocator, optional): Pre-built global OSMPP locator to reuse as
                the power plant database (ppdb). Defaults to None, in which case a new locator
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
            gem_loc=gem_loc,
            ppdb_loc=osmpp_loc,
            osm_update=osm_update,
            osm_live=osm_live,
        )

        self.ppdb_loc: OSMPPLocator = (  # type: ignore[assignment]
            self.ppdb_loc if self.ppdb_loc is not None else OSMPPLocator()
        )

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

        Reduces each unit's name to its discriminative tokens, so e.g. "Plant X Unit 1" and
        "Plant X Unit 2" group together.
        Known, accepted limitation: two genuinely different plants that reduce to the same
        base name will incorrectly group (if there is no unique per-plant ID to fall back on).

        todo: we may have other kinds of unique IDs aside from EIC/WeicCodes; not sure if
         these can be used to form groups though!

        Args:
            df (pd.DataFrame): The working dataframe.

        Returns:
            pd.Series: The derived EGE group key name.
        """

        def _base_key(name: object) -> str | None:
            """Derive the base key from the EGE name by reducing to its discriminative tokens.

            Example: "Mauá 3" / "Mauá Bloco 4" / "Mauá Bloco 5A" -> "maua"

            Args:
                name (str | None): The EGE name.

            Returns:
                str | None: The base key if it can be found, otherwise None.
            """
            clean_name = strip_str(name)
            if clean_name is None:
                return None

            wt = self.tok.weighted_tokenize(clean_name)
            full_tokens = [
                tok
                for tok, ttype in zip(wt.tokens, wt.types)
                if ttype == "discriminator"
            ]
            base = " ".join(full_tokens).strip()
            return base or None

        return df[self.sysop_name_col].map(
            lambda v: f"name_base:{k}" if (k := _base_key(v)) else None
        )
