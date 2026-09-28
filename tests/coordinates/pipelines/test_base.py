# tests/coordinates/pipelines/test_base.py
"""Structural tests for BasePipeline's shared scaffolding (not pipeline-specific steps)."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pandas as pd
import pytest

from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.natural_earth import RegionRegistry
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.mappings import (
    OPERATOR_COLUMNS,
    OPERATOR_METADATA,
    SYSOP_CODE_COL,
    SYSOP_FUEL_COL,
    SYSOP_FUEL_SUB_COL,
    SYSOP_NAME_COL,
    SYSOP_REGION_COL,
    OperatorInfo,
)
from rbc.coordinates.match_schema import MatchCandidate
from rbc.coordinates.pipelines._base import BasePipeline

BASE_MODULE = "rbc.coordinates.pipelines._base"


# ----------------------------------
# Fixtures / test doubles
# ----------------------------------
@pytest.fixture
def eia_csv_dir(tmp_path: Path) -> Path:
    """A real "eia" operator directory (no CSVs needed for structural tests).

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        Path: The EIA subdirectory that would normally contain CSV files.
    """
    csv_dir = Path(tmp_path, "eia", "1h")
    csv_dir.mkdir(parents=True)
    return csv_dir


def _make_candidate() -> MatchCandidate:
    """Build a minimal GEM candidate for the fuzzy step to write into the df.

    Returns:
        MatchCandidate: One candidate with the fields `_write_candidate_into_df` needs.
    """
    return MatchCandidate(
        name="Plant A",
        primary_name="Plant A",
        norm_name="plant a",
        wt_string="plant:1.0",
        locator="gem",
        id="gem-1",
        fueltype="hydro",
        capacity=None,
        status=None,
        url=None,
        lat=1.0,
        lon=2.0,
        country="Brazil",
    )


class _DummyPipeline(BasePipeline):
    """Minimal concrete BasePipeline subclass for checking shared ALL_STEPS loop.

    Overrides `BasePipeline`'s load/finalize steps so only the child STEPS-running mechanism
    itself is tested, not pipeline-specific behavior. BasePipeline's prep is used directly.
    """

    STEPS = ["_step_individual"]
    call_log: list[str] = []

    def _step_load_and_dedupe(self, df: pd.DataFrame) -> pd.DataFrame:
        self.call_log.append("load")
        return pd.DataFrame({"respondent-name": ["Plant A"]})  # eia's own name header

    def _step_individual(self, df: pd.DataFrame) -> pd.DataFrame:
        self.call_log.append("individual")
        return df

    def _step_finalize(self, df: pd.DataFrame) -> pd.DataFrame:
        self.call_log.append("finalize")
        return df


class _StopsEarlyPipeline(BasePipeline):
    """Concrete subclass using the real (inherited) `_step_load_and_dedupe`."""

    STEPS = ["_step_flag"]
    later_step_called: bool = False

    def _step_flag(self, df: pd.DataFrame) -> pd.DataFrame:
        self.later_step_called = True
        return df


# ----------------------------------
# Tests
# ----------------------------------
def test_operator_pipelines() -> None:
    """Happy path for mappings, checking that only entsoe uses a non-"default" pipeline."""
    assert OPERATOR_METADATA["entsoe"].get("pipeline", "default") == "entsoe"
    assert OPERATOR_METADATA["eia"].get("pipeline", "default") == "default"
    assert OPERATOR_METADATA["adme"].get("pipeline", "default") == "default"


def test_operator_columns_are_operatorinfo_keys() -> None:
    """Happy path: every OPERATOR_COLUMNS key must be a key of OperatorInfo.

    Each key is looked up on an operator's metadata to find its column. A key that doesn't
    exist on OperatorInfo finds nothing for every operator, silently dropping that column
    from matching and the output (as happened twice: "name_col" vs "entity_col", then
    "fuel_sub_col" vs "fuel_subtype_col").
    """
    assert set(OPERATOR_COLUMNS) <= set(OperatorInfo.__annotations__)


class TestBasePipelineInit:
    """Tests for BasePipeline initialization."""

    def test_no_direct_instantiation(self, eia_csv_dir: Path) -> None:
        """Failure path to check that BasePipeline cannot be instantiated directly.

        Args:
            eia_csv_dir (Path): Path to the EIA CSV directory.
        """
        with pytest.raises(TypeError, match="BasePipeline must be subclassed"):
            BasePipeline(
                input_dir=eia_csv_dir, output_dir=None, gem_loc=None, ppdb_loc=None
            )


class TestBasePipelineFuzzyMatch:
    """Tests for BasePipeline's shared fuzzy matching step."""

    def test_matcher_gets_the_pipelines_region_index(self, eia_csv_dir: Path) -> None:
        """Happy path: the name matcher checks regions with the pipeline's own index.

        If it built its own instead, every zone would read the admin-1 data again and
        ignore the run's `resources_dir` and `--update`.

        Args:
            eia_csv_dir (Path): Path to the (empty) EIA CSV directory.
        """
        region_reg = RegionRegistry()
        pipeline = _DummyPipeline(
            input_dir=eia_csv_dir,
            output_dir=None,
            gem_loc=None,
            ppdb_loc=None,
            region_reg=region_reg,
        )

        with patch(f"{BASE_MODULE}.NameMatcher") as mock_matcher:
            pipeline._step_fuzzy_match(pd.DataFrame())

        assert mock_matcher.call_args.kwargs["region_reg"] is region_reg

    def test_matcher_gets_the_locators_candidate_frames(
        self, eia_csv_dir: Path
    ) -> None:
        """Happy path: the pipeline hands each locator's rows to the matcher.

        The matcher takes frames rather than locator objects, so a locator whose frame
        is not passed on contributes no candidates at all -- and quietly, since None is
        a valid argument.

        Args:
            eia_csv_dir (Path): Path to the (empty) EIA CSV directory.
        """
        gem_frame = pd.DataFrame([{"plant_name": "Plant A"}])
        ppdb_frame = pd.DataFrame([{"Name": "Plant B"}])
        pipeline = _DummyPipeline(
            input_dir=eia_csv_dir,
            output_dir=None,
            gem_loc=cast(GEMLocator, SimpleNamespace(df=gem_frame)),
            ppdb_loc=cast(OSMPPLocator, SimpleNamespace(df=ppdb_frame)),
        )

        with patch(f"{BASE_MODULE}.NameMatcher") as mock_matcher:
            pipeline._step_fuzzy_match(pd.DataFrame())

        kwargs = mock_matcher.call_args.kwargs
        assert kwargs["gem_df"] is gem_frame
        assert kwargs["ppdb_df"] is ppdb_frame

    @pytest.mark.parametrize("via", ["name_exact", "name_fuzzy"])
    def test_match_method_names_the_approach(self, eia_csv_dir: Path, via: str) -> None:
        """Happy path: the written match_method says how the name was matched.

        The value has to distinguish a key hit from token scoring, since a reviewer
        judges a match's trustworthiness by it (s. MATCH_METHOD_COLORS).

        Args:
            eia_csv_dir (Path): Path to the (empty) EIA CSV directory.
            via (str): Parametrized approach the matcher reports.
        """
        pipeline = _DummyPipeline(
            input_dir=eia_csv_dir, output_dir=None, gem_loc=None, ppdb_loc=None
        )
        df = pd.DataFrame({SYSOP_NAME_COL: ["Plant A"], SYSOP_FUEL_COL: ["hydro"]})
        candidate = _make_candidate()
        result = SimpleNamespace(
            matched=True,
            candidate=candidate,
            score=100.0,
            matched_via=via,
            to_dicts=lambda **kwargs: [],
        )

        with patch(f"{BASE_MODULE}.NameMatcher") as mock_matcher:
            mock_matcher.return_value.match.return_value = result
            out = pipeline._step_fuzzy_match(df)

        assert out.loc[0, "gem.match_method"] == f"gem_{via}"


class TestBasePipelineRunPipeline:
    """Tests for BasePipeline's run_pipeline method."""

    def test_executes_steps_in_order(self, eia_csv_dir: Path) -> None:
        """Happy path: run_pipeline calls ALL_STEPS entries, in order, exactly once.

        Verifies both the pipeline-specific STEPS and the automatic BasePipeline predefined
        load & finalize steps. The real `_step_prepare_matching` runs in between "load" and
        "individual" (publishing eia's own name header as "sysop.name", so that is checked).

        Args:
            eia_csv_dir (Path): Path to the (empty) EIA CSV directory.
        """
        pipeline = _DummyPipeline(
            input_dir=eia_csv_dir, output_dir=None, gem_loc=None, ppdb_loc=None
        )
        df = pipeline.run_pipeline()

        assert pipeline.call_log == ["load", "individual", "finalize"]
        assert list(df[SYSOP_NAME_COL]) == ["Plant A"]

    def test_stops_early_when_load_and_dedupe_is_empty(self, eia_csv_dir: Path):
        """Failure path: run_pipeline stops early when the first step returns empty.

        Args:
            eia_csv_dir (Path): Path to the (empty) EIA CSV directory.
        """
        pipeline = _StopsEarlyPipeline(
            input_dir=eia_csv_dir, output_dir=None, gem_loc=None, ppdb_loc=None
        )
        df = pipeline.run_pipeline()

        assert df.empty
        assert pipeline.later_step_called is False

    def test_sysop_columns_are_generic(self, eia_csv_dir: Path) -> None:
        """Happy path: Relevant operator columns are renamed to generic "sysop.*".

        EIA names these "respondent-name"/"respondent"/"fueltype", but every operator
        publishes them under the same headers so runs stay comparable. Columns EIA doesn't
        have (e.g. fuel subtype, region) must produce no column at all, not an empty one.

        Args:
            eia_csv_dir (Path): Path to the (empty) EIA CSV directory.
        """
        df_raw = pd.DataFrame(
            {"respondent-name": ["Plant A"], "respondent": ["P1"], "fueltype": ["NG"]}
        )
        pipeline = _DummyPipeline(
            input_dir=eia_csv_dir, output_dir=None, gem_loc=None, ppdb_loc=None
        )
        df_prep = pipeline._step_prepare_matching(df_raw)

        # operators' headers are converted to generic "sysop.*" ones
        assert {SYSOP_NAME_COL, SYSOP_CODE_COL, SYSOP_FUEL_COL} <= set(df_prep.columns)
        assert not set(df_raw.columns) & set(df_prep.columns)

        # columns that the operator doesn't have configured don't exist in "sysop.*" form
        assert SYSOP_FUEL_SUB_COL not in df_prep.columns
        assert SYSOP_REGION_COL not in df_prep.columns

    def test_no_recognizable_operator_in_directory(self, tmp_path: Path) -> None:
        """Failure path: a directory has no recognizable operator in its parts.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        unknown_dir = Path(tmp_path, "not_a_real_operator")
        unknown_dir.mkdir()

        with pytest.raises(ValueError, match="No country match found"):
            _DummyPipeline(
                input_dir=unknown_dir, output_dir=None, gem_loc=None, ppdb_loc=None
            )
