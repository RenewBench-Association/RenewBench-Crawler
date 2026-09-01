# tests/coordinates/pipelines/test_entsoe.py
"""Tests for EntsoePipeline's declarative pipeline steps."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pandas as pd
import pytest

from rbc.coordinates.locators.eic_registry import EICCodeRegistry
from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.mappings import OPERATOR_METADATA
from rbc.coordinates.pipelines.entsoe import EntsoePipeline

NAME_COL = OPERATOR_METADATA["entsoe"].get("entity_col")
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

    eic_reg/ppdb_loc/gem_loc are all faked to avoid the real network/CSV fetches
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
    # skip the live Overpass call by pre-populating osm_df (before _step_fuzzy_match)
    pipeline.osm_df = pd.DataFrame(
        [
            {
                "Name": "Unrelated OSM Plant",
                "Fueltype": "Coal",
                "lat": 10.0,
                "lon": 10.0,
                "OSM_ID": "osm-x",
                "OSM_Type": "way",
                "OSM_URL": "",
                "OSM_Geometry": "",
            }
        ]
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
        for col in ("lat", "lon", "match_source"):
            assert col in df.columns


class TestEntsoePipelineSteps:
    """Tests for EntsoePipeline's step methods."""

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

    def test_derive_plant_group_key_eic(self, entsoe_pipeline: EntsoePipeline) -> None:
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
        keys = entsoe_pipeline._derive_plant_group_key_eic(df)
        assert keys.iloc[0] == keys.iloc[1]  # same resolved parent EIC -> same key
        assert keys.iloc[2] != keys.iloc[0]  # unrelated plant -> different key
