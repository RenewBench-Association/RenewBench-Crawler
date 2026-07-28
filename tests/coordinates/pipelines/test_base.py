# tests/coordinates/pipelines/test_base.py
"""Structural tests for BasePipeline's shared scaffolding (not pipeline-specific steps)."""

from pathlib import Path

import pandas as pd
import pytest

from rbc.coordinates.mappings import OPERATOR_METADATA
from rbc.coordinates.pipelines._base import BasePipeline


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


class _DummyPipeline(BasePipeline):
    """Minimal concrete BasePipeline subclass for checking shared STEPS loop independently."""

    STEPS = ["_step_one", "_step_two"]
    call_log: list[str]

    def _step_one(self, df: pd.DataFrame) -> pd.DataFrame:
        self.call_log.append("one")
        return pd.DataFrame({"x": [1]})

    def _step_two(self, df: pd.DataFrame) -> pd.DataFrame:
        self.call_log.append("two")
        return df


class _StopsEarlyPipeline(BasePipeline):
    """Concrete subclass using the real (inherited) `_step_load_and_dedupe`."""

    STEPS = ["_step_load_and_dedupe", "_step_flag"]
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


class TestBasePipelineInit:
    """Tests for BasePipeline initialization."""

    def test_no_direct_instantiation(self, eia_csv_dir: Path) -> None:
        """Failure path to check that BasePipeline cannot be instantiated directly.

        Args:
            eia_csv_dir (Path): Path to the EIA CSV directory.
        """
        with pytest.raises(TypeError, match="BasePipeline must be subclassed"):
            BasePipeline(
                input_dir=eia_csv_dir, output_dir=None, gemloc=None, ppmloc=None
            )


class TestBasePipelineRunPipeline:
    """Tests for BasePipeline's run_pipeline method."""

    def test_executes_steps_in_order(self, eia_csv_dir: Path) -> None:
        """Happy path: run_pipeline calls each STEPS entry, in order, exactly once.

        Args:
            eia_csv_dir (Path): Path to the (empty) EIA CSV directory.
        """
        pipeline = _DummyPipeline(
            input_dir=eia_csv_dir, output_dir=None, gemloc=None, ppmloc=None
        )
        pipeline.call_log = []

        df = pipeline.run_pipeline()

        assert pipeline.call_log == ["one", "two"]
        assert list(df["x"]) == [1]

    def test_stops_early_when_load_and_dedupe_is_empty(self, eia_csv_dir: Path):
        """Failure path: run_pipeline stops early when the first step returns empty.

        Args:
            eia_csv_dir (Path): Path to the (empty) EIA CSV directory.
        """
        pipeline = _StopsEarlyPipeline(
            input_dir=eia_csv_dir, output_dir=None, gemloc=None, ppmloc=None
        )

        df = pipeline.run_pipeline()

        assert df.empty
        assert pipeline.later_step_called is False

    def test_sysop_columns_are_prefixed(self, eia_csv_dir: Path) -> None:
        """Happy path: sysop_*_col properties prefix eia's real OPERATOR_METADATA columns.

        Args:
            eia_csv_dir (Path): Path to the (empty) EIA CSV directory.
        """
        pipeline = _DummyPipeline(
            input_dir=eia_csv_dir, output_dir=None, gemloc=None, ppmloc=None
        )

        assert pipeline.sysop_name_col == "sysop.respondent-name"
        assert pipeline.sysop_code_col == "sysop.respondent"
        assert pipeline.sysop_fuel_col == "sysop.fueltype"

    def test_no_recognizable_operator_in_directory(self, tmp_path: Path) -> None:
        """Failure path: a directory has no recognizable operator in its parts.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        unknown_dir = Path(tmp_path, "not_a_real_operator")
        unknown_dir.mkdir()

        with pytest.raises(ValueError, match="No country match found"):
            _DummyPipeline(
                input_dir=unknown_dir, output_dir=None, gemloc=None, ppmloc=None
            )
