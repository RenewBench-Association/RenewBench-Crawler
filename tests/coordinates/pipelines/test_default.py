# tests/coordinates/pipelines/test_default.py
"""Tests for DefaultPipeline's declarative pipeline steps."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pandas as pd
import pytest

from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.pipelines.default import DefaultPipeline


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def eia_input_dir(tmp_path: Path) -> Path:
    """Writes a small synthetic eia-shaped CSV to a real "eia" operator directory.

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        Path: The EIA subdirectory containing an exemplary CSV file.
    """
    csv_dir = Path(tmp_path, "eia", "1h")
    csv_dir.mkdir(parents=True)
    df = pd.DataFrame(
        [
            {
                "respondent-name": "Riverside Plant Unit 1",
                "respondent": "R1",
                "fueltype": "NG",
            },
            {
                "respondent-name": "Riverside Plant Unit 2",
                "respondent": "R2",
                "fueltype": "NG",
            },
        ]
    )
    df.to_csv(Path(csv_dir, "2024-01-01.csv"), index=False)
    return csv_dir


@pytest.fixture
def eia_pipeline(eia_input_dir: Path, tmp_path: Path) -> DefaultPipeline:
    """Returns a real DefaultPipeline for "eia", backed entirely by fake locators.

    Args:
        eia_input_dir (Path): The EIA subdirectory containing an exemplary CSV file.
        tmp_path (Path): Pytest-provided temporary directory, used for output_dir.

    Returns:
        DefaultPipeline: Default pipeline class instance for "eia" operator.
    """
    pipeline = DefaultPipeline(
        input_dir=eia_input_dir,
        output_dir=Path(tmp_path, "out"),
        gem_loc=cast(
            GEMLocator,
            SimpleNamespace(
                df_gem=pd.DataFrame(
                    [
                        {
                            "plant_name": "Riverside Plant",
                            "other_names": "",
                            "Country": "United States",
                            "Fueltype": "Natural Gas",
                            "lat": 40.0,
                            "lon": -90.0,
                            "gem_unit_id": "gem-us-1",
                        }
                    ]
                )
            ),
        ),
        osmpp_loc=cast(
            OSMPPLocator,
            SimpleNamespace(
                df=pd.DataFrame(
                    columns=["Name", "Country", "Fueltype", "lat", "lon", "id"]
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
class TestDefaultPipelineRunPipeline:
    """Tests for DefaultPipeline's run_pipeline method."""

    def test_run_pipeline_end_to_end(self, eia_pipeline: DefaultPipeline) -> None:
        """Happy path: the full default pipeline runs end-to-end without error.

        No real eia test data is available locally to verify actual match
        quality -- this proves the wiring holds together (load&dedupe -> fuzzy
        match against GEM+OSM -> fuel validation -> sibling fallback ->
        finalize) using synthetic data, entirely offline.

        Args:
            eia_pipeline (DefaultPipeline): Default pipeline class instance for "eia".
        """
        df = eia_pipeline.run_pipeline()
        assert len(df) == 2
        for col in ("lat", "lon", "match_source"):
            assert col in df.columns

        # no row should be attributed to a ppdb.* source.
        assert not df["match_source"].astype(str).str.startswith("ppdb").any()


class TestDefaultPipelineSteps:
    """Tests for DefaultPipeline's step methods."""

    def test_load_and_dedupe_uses_code_col(self, eia_pipeline: DefaultPipeline) -> None:
        """Happy path: dedupe uses code_col when the operator has one (e.g. eia).

        Args:
            eia_pipeline (DefaultPipeline): Default pipeline class instance for "eia".
        """
        df = eia_pipeline._step_load_and_dedupe(pd.DataFrame())
        assert len(df) == 2  # both rows have distinct respondent codes
        assert list(df.columns) == ["respondent-name", "respondent", "fueltype"]

    def test_load_and_dedupe_fallback_to_name(
        self, eia_pipeline: DefaultPipeline
    ) -> None:
        """Failure path: with no code_col, dedupe falls back to name_col.

        Args:
            eia_pipeline (DefaultPipeline): Default pipeline class instance for "eia".
                code_col is overridden to None here.
        """
        eia_pipeline.code_col = None
        df = eia_pipeline._step_load_and_dedupe(pd.DataFrame())
        assert len(df) == 2  # both rows have distinct respondent-name values too
        assert set(df["respondent-name"]) == {
            "Riverside Plant Unit 1",
            "Riverside Plant Unit 2",
        }


class TestDefaultPipelineHelpers:
    """Tests for DefaultPipeline's helper methods."""

    def test_derive_plant_group_key_name_groups_siblings(
        self, eia_pipeline: DefaultPipeline
    ) -> None:
        """Happy path: units sharing a base name get the same group key, others don't.

        Args:
            eia_pipeline (DefaultPipeline): Default pipeline class instance for "eia".
        """
        df = pd.DataFrame(
            {
                "sysop.respondent-name": [
                    "Riverside Plant Unit 1",
                    "Riverside Plant Unit 2",
                    "Downtown Station",
                ]
            }
        )
        keys = eia_pipeline._derive_plant_group_key_name(df)
        assert keys.iloc[0] == keys.iloc[1]  # same base name -> same key
        assert keys.iloc[2] != keys.iloc[0]  # unrelated plant -> different key
        assert keys.iloc[0] is not None and str(keys.iloc[0]).startswith("name_base:")

    def test_sibling_fallback_core_inherits_coords_from_matched_sibling(
        self, eia_pipeline: DefaultPipeline
    ) -> None:
        """Happy path for the shared sibling-fallback machinery, independent of key strategy.

        Args:
            eia_pipeline (DefaultPipeline): Default pipeline class instance for "eia".
        """
        df = pd.DataFrame(
            {
                "sysop.respondent-name": ["Matched Unit", "Needs Sibling Unit"],
                "ppdb.lat": [40.0, None],
                "ppdb.lon": [-90.0, None],
                "gem.lat": [None, None],
                "gem.lon": [None, None],
                "osm.lat": [None, None],
                "osm.lon": [None, None],
            }
        )
        plant_group_key = pd.Series(["group:x", "group:x"])
        result = eia_pipeline._sibling_fallback_core(df, plant_group_key)
        assert result.loc[1, "sibling.lat"] == 40.0
        assert result.loc[1, "sibling.lon"] == -90.0
        assert pd.isna(
            result.loc[0, "sibling.lat"]
        )  # already matched, no fallback needed

    def test_base_name_key_collapses_sibling_units(
        self, eia_pipeline: DefaultPipeline
    ) -> None:
        """Happy path: units differing only by a unit designator share one base key.

        Args:
            eia_pipeline (DefaultPipeline): Default pipeline class instance for "eia".
        """
        assert eia_pipeline.base_name_key(
            "Plant X Unit 1"
        ) == eia_pipeline.base_name_key("Plant X Unit 2")

    def test_base_name_key_all_generic_returns_none(
        self, eia_pipeline: DefaultPipeline
    ) -> None:
        """Failure path: a name with no discriminative tokens has no base key.

        Every weighting rule that can classify a token LOW_WEIGHT (vocabulary
        membership, or the bare-1-2-letter/1-3-digit designator pattern)
        guarantees any surviving DEFAULT_WEIGHT token is already >=3 chars, so
        an explicit length guard on the joined key would be unreachable -- this
        case (zero survivors) is the only way to end up with no usable key.

        Args:
            eia_pipeline (DefaultPipeline): Default pipeline class instance for "eia".
        """
        assert eia_pipeline.base_name_key("Unit 1") is None
        assert eia_pipeline.base_name_key("Q1") is None
