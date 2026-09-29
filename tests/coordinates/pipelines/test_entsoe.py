# tests/coordinates/pipelines/test_entsoe.py
"""Tests for EntsoePipeline's declarative pipeline steps."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pandas as pd
import pytest

from rbc.coordinates.mappings import OPERATOR_METADATA, SYSOP_CODE_COL
from rbc.coordinates.match_schema import MatchCandidate
from rbc.coordinates.pipelines.entsoe import (
    WCODE_LONGNAME,
    WCODE_PARENT,
    EntsoePipeline,
)
from rbc.coordinates.resources.eic import EICCodeRegistry
from rbc.coordinates.resources.gem import GEMLocator
from rbc.coordinates.resources.overpass import OverpassLocator
from rbc.coordinates.resources.ppm import PPMLocator

NAME_COL = OPERATOR_METADATA["entsoe"].get("name_col")
CODE_COL = OPERATOR_METADATA["entsoe"].get("code_col")
FUEL_COL = OPERATOR_METADATA["entsoe"].get("fuel_col")


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def entsoe_input_dir(tmp_path: Path) -> Path:
    """Writes a small synthetic entsoe-shaped CSV to a real ENTSO-E zone directory.

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        Path: The "entsoe/10YNL----------L" zone directory containing the CSV.
    """
    zone_dir = Path(tmp_path, "entsoe", "10YNL----------L")
    zone_dir.mkdir(parents=True)
    df = pd.DataFrame(
        [
            {
                NAME_COL: "Riverside Unit 1",
                CODE_COL: "11W-RIVERSIDE1-A",
                FUEL_COL: "B14",
            },
            {
                NAME_COL: "Riverside Unit 2",
                CODE_COL: "11W-RIVERSIDE2-B",
                FUEL_COL: "B14",
            },
        ]
    )
    df.to_csv(Path(zone_dir, "2024-01-01.csv"), index=False)
    return zone_dir


@pytest.fixture
def entsoe_pipeline(entsoe_input_dir: Path, tmp_path: Path) -> EntsoePipeline:
    """Returns a real EntsoePipeline for "10YNL----------L", backed by fake locators.

    eic_reg/ppdb_loc/gem_loc/osm_loc are all faked to avoid the real network/CSV fetches
    their real constructors would otherwise perform, and to keep every
    exact-ID lookup a clean miss so the pipeline falls through to fuzzy
    matching against the fake GEM data.

    Args:
        entsoe_input_dir (Path): Synthetic "entsoe/10YNL----------L" zone directory.
        tmp_path (Path): Pytest-provided temporary directory, used for output_dir.

    Returns:
        EntsoePipeline: Entsoe pipeline class instance for the "NL" zone.
    """
    pipeline = EntsoePipeline(
        input_dir=entsoe_input_dir,
        output_dir=Path(tmp_path, "out"),
        gem_loc=cast(
            GEMLocator,
            cast(
                object,
                SimpleNamespace(
                    match_by_entsoe_id=lambda eic: None,
                    df=pd.DataFrame(
                        [
                            {
                                "plant_name": "Riverside Plant",
                                "other_names": "",
                                "Country": "Netherlands",
                                "Fueltype": "Nuclear",
                                "lat": 52.0,
                                "lon": 5.0,
                                "gem_unit_id": "gem-nl-1",
                            }
                        ]
                    ),
                ),
            ),
        ),
        ppm_loc=cast(
            PPMLocator,
            cast(
                object,
                SimpleNamespace(
                    match_by_entsoe_id=lambda eic: None,
                    df=pd.DataFrame(
                        columns=[
                            "Name",
                            "Country",
                            "Fueltype",
                            "lat",
                            "lon",
                            "id",
                            "EIC",
                        ]
                    ),
                ),
            ),
        ),
        osm_loc=cast(
            OverpassLocator,
            cast(
                object,
                SimpleNamespace(
                    get_country_df=lambda country_code: pd.DataFrame(
                        [
                            {
                                "Name": "Unrelated OSM Plant",
                                "Fueltype": "Coal",
                                "lat": 10.0,
                                "lon": 10.0,
                                "OSM_ID": "osm-x",
                                "OSM_Type": "way",
                                "OSM_URL": "",
                            }
                        ]
                    )
                ),
            ),
        ),
        eic_reg=cast(
            EICCodeRegistry,
            cast(
                object,
                SimpleNamespace(
                    WCODE_FIELDS=EICCodeRegistry.WCODE_FIELDS,
                    MATCH_FIELDS=EICCodeRegistry.MATCH_FIELDS,
                    lookup_full_row=lambda eic: {},
                    find_parent_production_unit=lambda **kwargs: None,
                ),
            ),
        ),
    )
    return pipeline


# ----------------------------------
# Tests
# ----------------------------------
class TestEntsoePipelineRunPipeline:
    """Tests for EntsoePipeline's run_pipeline method."""

    def test_run_pipeline_end_to_end(self, entsoe_pipeline: EntsoePipeline) -> None:
        """Happy path: the full entsoe pipeline runs end-to-end without error.

        No real EIC/PPM data is available locally to verify actual match
        quality -- this proves the wiring holds together (EIC lookup -> direct
        ID match -> parent resolution -> parent ID match -> fuzzy match against
        GEM -> fuel validation -> sibling fallback -> finalize) using synthetic
        data, entirely offline.

        Args:
            entsoe_pipeline (EntsoePipeline): Entsoe pipeline class instance for "NL".
        """
        df = entsoe_pipeline.run_pipeline()
        assert len(df) == 2
        for col in ("lat", "lon", "match_method"):
            assert col in df.columns


class TestEntsoePipelineSteps:
    """Tests for EntsoePipeline's step methods."""

    def test_eic_lookup_without_a_registry_still_publishes_columns(
        self, entsoe_input_dir: Path
    ) -> None:
        """Failure path: with no EIC directory, enrichment is skipped, its columns not.

        Later steps read the `wcode.*` columns directly, so they have to exist even when
        nothing could be looked up.

        Args:
            entsoe_input_dir (Path): The synthetic "entsoe/10YNL----------L" zone dir.
        """
        pipeline = EntsoePipeline(input_dir=entsoe_input_dir, eic_reg=None)
        df = pd.DataFrame([{SYSOP_CODE_COL: "11W-UNIT"}])

        out = pipeline._step_entsoe_eic_lookup(df)

        assert WCODE_LONGNAME in out.columns
        assert out[WCODE_LONGNAME].isna().all()

    @pytest.mark.parametrize(
        "locator, hit_code, expected",
        [
            ("gem_loc", "11W-UNIT", "gem_id_exact"),
            ("gem_loc", "11W-PARENT", "gem_id_parent_exact"),
            ("ppdb_loc", "11W-UNIT", "ppdb_id_exact"),
            ("ppdb_loc", "11W-PARENT", "ppdb_id_parent_exact"),
        ],
    )
    def test_match_by_id_names_the_code_it_matched(
        self,
        entsoe_pipeline: EntsoePipeline,
        locator: str,
        hit_code: str,
        expected: str,
    ) -> None:
        """Happy path: each EIC branch records which code found the match, and where.

        The four branches are otherwise indistinguishable in the output, while a parent
        match says something weaker about the EGE than its own code matching does.

        Args:
            entsoe_pipeline (EntsoePipeline): Entsoe pipeline class instance for "NL".
            locator (str): Attribute name of the locator whose lookup hits.
            hit_code (str): The EIC code that the lookup answers to (unit or parent).
            expected (str): The match_method value expected in the output.
        """
        candidate = MatchCandidate(
            name="Riverside Plant",
            primary_name="Riverside Plant",
            norm_name="riverside plant",
            wt_string="riverside:1.0",
            locator="gem" if locator == "gem_loc" else "ppdb",
            id="loc-1",
            fueltype="Nuclear",
            capacity=None,
            status=None,
            url=None,
            lat=52.0,
            lon=5.0,
            country="Netherlands",
        )
        getattr(entsoe_pipeline, locator).match_by_entsoe_id = lambda eic: (
            candidate if eic == hit_code else None
        )
        df = pd.DataFrame([{SYSOP_CODE_COL: "11W-UNIT", WCODE_PARENT: "11W-PARENT"}])
        entsoe_pipeline._create_match_method_columns(df)

        out = entsoe_pipeline._step_entsoe_match_by_id(df)

        assert out.loc[0, f"{candidate.locator}.match_method"] == expected

    def test_load_and_dedupe_uses_code_col(
        self, entsoe_pipeline: EntsoePipeline
    ) -> None:
        """Happy path: dedupe uses code_col (entsoe always has one).

        Args:
            entsoe_pipeline (EntsoePipeline): Entsoe pipeline class instance for "NL".
        """
        df = entsoe_pipeline._step_load_and_dedupe(pd.DataFrame())
        assert len(df) == 2
        assert list(df.columns) == [NAME_COL, CODE_COL, FUEL_COL]


class TestEntsoePipelineHelpers:
    """Tests for EntsoePipeline's helper methods."""

    def test_derive_ege_group_key_id(self, entsoe_pipeline: EntsoePipeline) -> None:
        """Happy path: units sharing a resolved parent EIC get the same group key.

        Args:
            entsoe_pipeline (EntsoePipeline): Entsoe pipeline class instance for "NL".
        """
        df = pd.DataFrame(
            {
                "sysop.": [
                    "Riverside Plant Unit 1",
                    "Riverside Plant Unit 2",
                    "Other Plant",
                ],
                "wcode.EicParent": [None, None, None],
                "wcode.parent.EicCode": ["11W-PARENT-----X", "11W-PARENT-----X", None],
                "wcode.EicLongName": [None, None, "Other Plant"],
                "wcode.EicDisplayName": [None, None, None],
            }
        )
        keys = entsoe_pipeline._derive_ege_group_key_id(df)
        assert keys.iloc[0] == keys.iloc[1]  # same resolved parent EIC -> same key
        assert keys.iloc[2] != keys.iloc[0]  # unrelated plant -> different key
