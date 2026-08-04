# tests/weather/regridding/test_base.py
"""Tests for rbc.weather.regridding.base: GridRegridder ABC."""

import pickle
from pathlib import Path
from unittest.mock import patch

import pytest
import xarray as xr

from rbc.weather.regridding.base import GridRegridder


# ----------------------------------
# Minimal concrete subclass for testing
# ----------------------------------
class _ConcreteRegridder(GridRegridder):
    """Minimal concrete implementation of GridRegridder used only in tests.

    Attributes:
        _tasks (list[tuple]): Task list returned by _get_tasks.
        _source_ds (xr.Dataset): Dataset returned by _load_source_chunk.
        _grid_path (Path | None): Path returned by _grid_metadata_path.
        _mapping (dict[str, str]): Mapping returned by _variable_mapping.
    """

    def __init__(
        self,
        tasks: list[tuple] | None = None,
        source_ds: xr.Dataset | None = None,
        grid_path: Path | None = None,
        mapping: dict[str, str] | None = None,
        **kwargs,
    ) -> None:
        """Initialise the regridder with fixed test doubles.

        Args:
            tasks (list[tuple] | None): Task tuples returned by _get_tasks.
                Defaults to an empty list when None.
            source_ds (xr.Dataset | None): Dataset returned by
                _load_source_chunk. Defaults to a tiny synthetic Dataset.
            grid_path (Path | None): Path returned by _grid_metadata_path.
            mapping (dict[str, str] | None): Mapping returned by
                _variable_mapping. Defaults to an empty dict.
            **kwargs: Forwarded to GridRegridder.__init__.
        """
        self._tasks = tasks or []
        self._source_ds = (
            source_ds
            if source_ds is not None
            else xr.Dataset({"foo": ("x", [1, 2, 3])})
        )
        self._grid_path = grid_path
        self._mapping = mapping or {}
        super().__init__(**kwargs)

    def _get_tasks(self) -> list[tuple]:
        """Return the pre-defined task list supplied at construction time."""
        return self._tasks

    def _load_source_chunk(self, task: tuple) -> xr.Dataset:
        """Return the pre-defined source Dataset, regardless of task."""
        return self._source_ds

    def _grid_metadata_path(self) -> Path | None:
        """Return the pre-defined grid metadata path."""
        return self._grid_path

    def _variable_mapping(self) -> dict[str, str]:
        """Return the pre-defined variable mapping."""
        return self._mapping


class _Incomplete(GridRegridder):
    """Subclass deliberately missing _variable_mapping, for ABC enforcement tests."""

    def _load_source_chunk(self, task: tuple) -> xr.Dataset:
        """Return an empty Dataset."""
        return xr.Dataset()

    def _grid_metadata_path(self) -> Path | None:
        """Return None."""
        return None

    # _variable_mapping intentionally omitted


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def base_args(tmp_path: Path) -> dict:
    """Provide minimal valid keyword arguments for _ConcreteRegridder.

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        dict: Keyword arguments passed directly to _ConcreteRegridder.
    """
    raw_dir = Path(tmp_path, "raw")
    raw_dir.mkdir()
    return {
        "raw_dir": raw_dir,
        "source_name": "test_source",
        "weights_cache_dir": Path(tmp_path, "weights_cache", "nested"),
        "min_level": 4,
        "max_level": 7,
        "variables": ["var_a"],
        "years": [2025],
        "months": ["01"],
    }


# ----------------------------------
# GridRegridder.__init__
# ----------------------------------
class TestInit:
    """Tests for GridRegridder.__init__.

    Covers attribute assignment, raw_dir/level validation, weights_cache_dir
    creation, and checkpoint initialisation.
    """

    def test_attributes_are_set(self, base_args: dict) -> None:
        """Core/derived attributes are set, and weights_cache_dir is created.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        rg = _ConcreteRegridder(**base_args)
        assert rg.source_name == "test_source"
        assert rg.min_level == 4
        assert rg.max_level == 7
        assert rg.variables == ["var_a"]
        assert rg.dry_run is False
        assert rg.resume is True
        assert rg.checkpoint_path == Path(rg.raw_dir, "regrid_status.pickle")
        assert rg.weights_cache_dir.is_dir()

    def test_raw_dir_missing_raises(self, tmp_path: Path, base_args: dict) -> None:
        """Missing raw_dir raises FileNotFoundError.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        base_args["raw_dir"] = Path(tmp_path, "does_not_exist")
        with pytest.raises(FileNotFoundError, match="does not exist"):
            _ConcreteRegridder(**base_args)

    @pytest.mark.parametrize("min_level, max_level", [(5, 5), (7, 4)])
    def test_min_level_not_below_max_level_raises(
        self, base_args: dict, min_level: int, max_level: int
    ) -> None:
        """min_level equal to or greater than max_level raises ValueError.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
            min_level (int): min_level value to test.
            max_level (int): max_level value to test.
        """
        base_args["min_level"] = min_level
        base_args["max_level"] = max_level
        with pytest.raises(ValueError, match="must be lower than"):
            _ConcreteRegridder(**base_args)

    def test_empty_checkpoint_on_fresh_start(self, base_args: dict) -> None:
        """Checkpoint is empty dict when no checkpoint file exists yet.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        rg = _ConcreteRegridder(**base_args)
        assert rg.checkpoint == {}

    def test_checkpoint_loaded_on_resume(self, base_args: dict) -> None:
        """Existing checkpoint is loaded when resume=True.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        saved = {(2025, 1): 1}
        checkpoint_path = Path(base_args["raw_dir"], "regrid_status.pickle")
        with open(checkpoint_path, "wb") as f:
            pickle.dump(saved, f)

        rg = _ConcreteRegridder(**base_args)
        assert rg.checkpoint == saved

    def test_checkpoint_ignored_when_resume_false(self, base_args: dict) -> None:
        """Existing checkpoint file is ignored when resume=False.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        saved = {(2025, 1): 1}
        checkpoint_path = Path(base_args["raw_dir"], "regrid_status.pickle")
        with open(checkpoint_path, "wb") as f:
            pickle.dump(saved, f)

        base_args["resume"] = False
        rg = _ConcreteRegridder(**base_args)
        assert rg.checkpoint == {}

    def test_corrupted_checkpoint_starts_fresh(self, base_args: dict) -> None:
        """Corrupted checkpoint file is discarded and a fresh checkpoint is returned.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        checkpoint_path = Path(base_args["raw_dir"], "regrid_status.pickle")
        checkpoint_path.write_bytes(b"not-valid-pickle-data")

        rg = _ConcreteRegridder(**base_args)
        assert rg.checkpoint == {}


# ----------------------------------
# GridRegridder._get_tasks (default implementation)
# ----------------------------------
class TestGetTasks:
    """Tests for GridRegridder._get_tasks()'s default implementation.

    _ConcreteRegridder overrides _get_tasks() with a fixed, test-injectable
    list for use elsewhere in this file, so the base class's own default is
    called directly here (bypassing that override) to test it in isolation.
    """

    def test_default_returns_year_month_cartesian_product(
        self, base_args: dict
    ) -> None:
        """Default _get_tasks() returns every (year, month) combination.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        base_args["years"] = [2024, 2025]
        base_args["months"] = ["01", "02"]
        rg = _ConcreteRegridder(**base_args)

        tasks = GridRegridder._get_tasks(rg)

        assert tasks == [(2024, "01"), (2024, "02"), (2025, "01"), (2025, "02")]

    def test_months_default_to_all_twelve(self, base_args: dict) -> None:
        """When months is not provided, all 12 zero-padded months are used.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        base_args["years"] = [2025]
        del base_args["months"]
        rg = _ConcreteRegridder(**base_args)

        tasks = GridRegridder._get_tasks(rg)

        assert tasks == [(2025, f"{i:02d}") for i in range(1, 13)]


# ----------------------------------
# GridRegridder.regrid
# ----------------------------------
class TestRegrid:
    """Tests for GridRegridder.regrid().

    Covers task iteration, checkpoint skip/resume, dry_run semantics, and the
    premature-checkpointing regression (regrid() must never mark tasks done).
    """

    def test_calls_pipeline_for_each_task(self, base_args: dict) -> None:
        """_get_weights/_regrid_chunk run once per task, yielding (task, pyramid).

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        tasks = [(2025, 1), (2025, 2)]
        rg = _ConcreteRegridder(tasks=tasks, **base_args)

        with (
            patch.object(rg, "_get_weights", return_value=Path("weights.nc")) as mock_w,
            patch.object(rg, "_regrid_chunk", return_value={4: "pyramid"}) as mock_c,
        ):
            results = list(rg.regrid())

        assert mock_w.call_count == 2
        assert mock_c.call_count == 2
        assert [task for task, _ in results] == tasks
        assert all(pyramid == {4: "pyramid"} for _, pyramid in results)

    def test_skips_already_completed_tasks(self, base_args: dict) -> None:
        """Tasks already marked 1 in checkpoint are skipped when resume=True.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        task = (2025, 1)
        rg = _ConcreteRegridder(tasks=[task], **base_args)
        rg.checkpoint[task] = 1

        with patch.object(rg, "_regrid_chunk") as mock_c:
            results = list(rg.regrid())

        mock_c.assert_not_called()
        assert results == []

    def test_resume_false_recomputes_even_if_checkpointed(
        self, base_args: dict
    ) -> None:
        """A checkpointed task is still recomputed when resume=False.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        task = (2025, 1)
        base_args["resume"] = False
        rg = _ConcreteRegridder(tasks=[task], **base_args)
        rg.checkpoint[task] = 1  # would be "done" under resume=True

        with (
            patch.object(rg, "_get_weights", return_value=Path("weights.nc")),
            patch.object(rg, "_regrid_chunk", return_value={4: "pyramid"}) as mock_c,
        ):
            results = list(rg.regrid())

        mock_c.assert_called_once()
        assert len(results) == 1

    def test_dry_run_resolves_but_does_not_yield(self, base_args: dict) -> None:
        """dry_run resolves weights but skips regridding and yielding.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        task = (2025, 1)
        base_args["dry_run"] = True
        rg = _ConcreteRegridder(tasks=[task], **base_args)

        with (
            patch.object(rg, "_get_weights", return_value=Path("weights.nc")) as mock_w,
            patch.object(rg, "_regrid_chunk") as mock_c,
        ):
            results = list(rg.regrid())

        mock_w.assert_called_once()
        mock_c.assert_not_called()
        assert results == []

    def test_regrid_does_not_mark_checkpoint_done(self, base_args: dict) -> None:
        """regrid() never writes to the checkpoint itself (see mark_done()).

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        task = (2025, 1)
        rg = _ConcreteRegridder(tasks=[task], **base_args)

        with (
            patch.object(rg, "_get_weights", return_value=Path("weights.nc")),
            patch.object(rg, "_regrid_chunk", return_value={4: "pyramid"}),
        ):
            list(rg.regrid())

        assert rg.checkpoint == {}

    def test_no_tasks_completes_without_error(self, base_args: dict) -> None:
        """regrid() completes cleanly when there are no tasks.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        rg = _ConcreteRegridder(tasks=[], **base_args)
        assert list(rg.regrid()) == []


# ----------------------------------
# GridRegridder.mark_done
# ----------------------------------
class TestMarkDone:
    """Tests for GridRegridder.mark_done().

    Verifies the checkpoint is updated in memory and persisted to disk, and
    that no temporary artefacts are left behind after a successful save.
    """

    def test_mark_done_sets_checkpoint_and_persists(self, base_args: dict) -> None:
        """mark_done sets the checkpoint in memory and persists it to disk.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        task = (2025, 1)
        rg = _ConcreteRegridder(tasks=[task], **base_args)
        rg.mark_done(task)

        assert rg.checkpoint[task] == 1

        fresh = _ConcreteRegridder(tasks=[task], **base_args)
        assert fresh.checkpoint[task] == 1

    def test_atomic_write_no_tmp_left_behind(self, base_args: dict) -> None:
        """Temporary .tmp file is removed after a successful save.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        rg = _ConcreteRegridder(**base_args)
        rg.mark_done((2025, 1))
        assert not rg.checkpoint_path.with_suffix(".tmp").exists()


# ----------------------------------
# GridRegridder._rename_to_canonical
# ----------------------------------
class TestRenameToCanonical:
    """Tests for GridRegridder._rename_to_canonical()."""

    def test_renames_present_and_skips_missing(self, base_args: dict) -> None:
        """Present variables are renamed; mapping entries absent from ds are skipped.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        ds = xr.Dataset({"T": ("x", [1, 2, 3]), "U": ("x", [4, 5, 6])})
        mapping = {"T": "temperature", "V": "v_wind"}  # V not in ds
        rg = _ConcreteRegridder(mapping=mapping, **base_args)

        renamed = rg._rename_to_canonical(ds)

        assert "temperature" in renamed.data_vars
        assert "T" not in renamed.data_vars
        assert "U" in renamed.data_vars  # untouched, not in mapping
        assert "v_wind" not in renamed.data_vars


# ----------------------------------
# GridRegridder._get_weights
# ----------------------------------
class TestGetWeights:
    """Tests for GridRegridder._get_weights().

    Covers the lat-lon path (weights from the dataset itself), the
    unstructured path (weights from a separate grid file), and the
    grid-metadata-coupling fail-fast guard.
    """

    def test_lat_lon_source_uses_dataset_directly(self, base_args: dict) -> None:
        """When _grid_metadata_path is None, weights are computed from ds itself.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        ds = xr.Dataset({"T": ("x", [1, 2, 3])})
        rg = _ConcreteRegridder(grid_path=None, **base_args)

        with patch("rbc.weather.regridding.base.gd.cached_weights") as mock_cached:
            mock_cached.return_value = Path("weights.nc")
            result = rg._get_weights(ds)

        mock_cached.assert_called_once_with(
            ds, level=rg.max_level, cache_path=rg.weights_cache_dir
        )
        assert result == Path("weights.nc")

    def test_unstructured_source_missing_grid_file_raises(
        self, tmp_path: Path, base_args: dict
    ) -> None:
        """A configured but missing grid file raises FileNotFoundError.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        ds = xr.Dataset({"T": ("x", [1, 2, 3])})
        missing_grid = Path(tmp_path, "missing_grid.nc")
        rg = _ConcreteRegridder(grid_path=missing_grid, **base_args)

        with patch("rbc.weather.regridding.base.gd.cached_weights") as mock_cached:
            with pytest.raises(FileNotFoundError, match="Grid metadata file not found"):
                rg._get_weights(ds)

        mock_cached.assert_not_called()

    def test_unstructured_source_uses_grid_file(
        self, tmp_path: Path, base_args: dict
    ) -> None:
        """When _grid_metadata_path exists, weights come from the grid file, not ds.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        ds = xr.Dataset({"T": ("x", [1, 2, 3])})
        grid_path = Path(tmp_path, "grid.nc")
        grid_path.write_bytes(b"fake")  # only existence is checked before open_dataset
        geometry_ds = xr.Dataset({"clon": ("cell", [0.1, 0.2])})
        rg = _ConcreteRegridder(grid_path=grid_path, **base_args)

        with (
            patch(
                "rbc.weather.regridding.base.xr.open_dataset", return_value=geometry_ds
            ) as mock_open,
            patch("rbc.weather.regridding.base.gd.cached_weights") as mock_cached,
        ):
            mock_cached.return_value = Path("weights.nc")
            rg._get_weights(ds)

        mock_open.assert_called_once_with(grid_path)
        mock_cached.assert_called_once_with(
            geometry_ds, level=rg.max_level, cache_path=rg.weights_cache_dir
        )


# ----------------------------------
# GridRegridder._regrid_chunk
# ----------------------------------
class TestRegridChunk:
    """Tests for GridRegridder._regrid_chunk()."""

    def test_forwards_correct_kwargs(self, base_args: dict) -> None:
        """min_level/max_level aren't swapped, and _regrid_kwargs() is forwarded.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        ds = xr.Dataset({"T": ("x", [1, 2, 3])})
        weights = Path("weights.nc")
        rg = _ConcreteRegridder(**base_args)

        with (
            patch.object(
                rg, "_regrid_kwargs", return_value={"source_kind": "unstructured"}
            ),
            patch(
                "rbc.weather.regridding.base.gd.create_healpix_pyramid"
            ) as mock_create,
        ):
            mock_create.return_value = {4: "pyramid"}
            rg._regrid_chunk(ds, weights)

        mock_create.assert_called_once_with(
            ds,
            max_level=rg.max_level,
            min_level=rg.min_level,
            weights_path=weights,
            source_kind="unstructured",
        )


# ----------------------------------
# GridRegridder — ABC enforcement
# ----------------------------------
class TestAbstractMethods:
    """Tests for GridRegridder ABC enforcement.

    Verifies that the abstract base class cannot be instantiated directly and
    that subclasses missing any abstract method raise TypeError.
    """

    def test_cannot_instantiate_abc_directly(self, base_args: dict) -> None:
        """GridRegridder itself cannot be instantiated (abstract).

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        with pytest.raises(TypeError):
            GridRegridder(**base_args)  # type: ignore[abstract]

    def test_subclass_missing_abstract_method_raises(self, base_args: dict) -> None:
        """A subclass that omits an abstract method cannot be instantiated.

        Args:
            base_args (dict): Minimal valid keyword arguments for _ConcreteRegridder.
        """
        with pytest.raises(TypeError):
            _Incomplete(**base_args)  # type: ignore[abstract]
