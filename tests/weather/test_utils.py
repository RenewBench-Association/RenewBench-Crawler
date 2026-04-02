# tests/weather/test_utils.py
"""Tests for rbc.weather.utils: WeatherDownloader ABC and download_file_streaming."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from rbc.weather.utils import WeatherDownloader, download_file_streaming


# ----------------------------------
# Minimal concrete subclass for testing
# ----------------------------------
class _ConcreteDownloader(WeatherDownloader):
    """Minimal concrete implementation of WeatherDownloader used only in tests.

    Stores a fixed task list and a mapping of pre-configured return values so
    tests can control download outcomes without using the network.

    Attributes:
        _tasks (list[tuple]): Task list returned by _get_tasks.
        _download_results (dict[tuple, int]): Maps task tuples to fixed return
            values (1 = success, 0 = failure). Defaults to 1 for unknown tasks.
    """

    def __init__(self, tasks: list[tuple] | None = None, **kwargs) -> None:
        """Initialise the downloader with a fixed task list.

        Args:
            tasks (list[tuple] | None): Task tuples returned by _get_tasks.
                Defaults to an empty list when None.
            **kwargs: Forwarded to WeatherDownloader.__init__.
        """
        self._tasks = tasks or []
        self._download_results: dict[tuple, int] = {}
        super().__init__(**kwargs)

    def _get_tasks(self) -> list[tuple]:
        """Return the pre-defined task list supplied at construction time.

        Returns:
            list[tuple]: Task tuples passed in at initialisation.
        """
        return self._tasks

    def _download_task(self, task: tuple) -> int:
        """Return the pre-configured result for a task.

        Args:
            task (tuple): Task tuple to look up in _download_results.

        Returns:
            int: 1 (success) by default, or the value stored in _download_results.
        """
        return self._download_results.get(task, 1)

    def _validate_variables(self) -> None:
        """No-op implementation, variable validation is not exercised here."""
        pass


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def base_args(tmp_path: Path) -> dict:
    """Provide minimal valid keyword arguments for _ConcreteDownloader.

    Args:
        tmp_path (Path): Pytest-provided temporary directory used as output_path.

    Returns:
        dict: Keyword arguments passed directly to _ConcreteDownloader.
    """
    return {
        "output_path": tmp_path,
        "years": [2020],
        "months": ["01"],
        "variables": ["var_a"],
        "dry_run": False,
        "resume": False,
    }


# ----------------------------------
# WeatherDownloader.__init__
# ----------------------------------
class TestInit:
    """Tests for WeatherDownloader.__init__.

    Covers attribute assignment, output_path creation, checkpoint initialisation,
    and year filtering by start_year.
    """

    def test_attributes_are_set(self, base_args: dict) -> None:
        """Core attributes are assigned correctly from constructor arguments."""
        dl = _ConcreteDownloader(**base_args)
        assert dl.years == [2020]
        assert dl.months == ["01"]
        assert dl.variables == ["var_a"]
        assert dl.dry_run is False
        assert dl.resume is False

    def test_output_path_created(self, tmp_path: Path, base_args: dict) -> None:
        """output_path directory is created if it does not exist."""
        base_args["output_path"] = Path(tmp_path, "new", "nested")
        dl = _ConcreteDownloader(**base_args)
        assert dl.output_path.is_dir()

    def test_checkpoint_path_set(self, base_args: dict) -> None:
        """checkpoint_path points to status.pickle inside output_path."""
        dl = _ConcreteDownloader(**base_args)
        assert dl.checkpoint_path == Path(dl.output_path, "status.pickle")

    def test_default_months_all_twelve(self, base_args: dict) -> None:
        """When months=None, all 12 months are set as zero-padded strings."""
        base_args["months"] = None
        dl = _ConcreteDownloader(**base_args)
        assert dl.months == [f"{i:02d}" for i in range(1, 13)]

    def test_years_sorted(self, base_args: dict) -> None:
        """Years are sorted regardless of the order they are passed in."""
        base_args["years"] = [2022, 2020, 2021]
        dl = _ConcreteDownloader(**base_args)
        assert dl.years == [2020, 2021, 2022]

    def test_start_year_filters_past_years(self, base_args: dict) -> None:
        """Years before start_year are silently filtered out."""
        base_args["years"] = [1800, 2020, 2021]
        dl = _ConcreteDownloader(**base_args, start_year=2000)
        assert dl.years == [2020, 2021]

    def test_start_year_filters_future_years(self, base_args: dict) -> None:
        """Years after the current year are silently filtered out."""
        base_args["years"] = [2020, 9999]
        dl = _ConcreteDownloader(**base_args, start_year=1900)
        assert 9999 not in dl.years
        assert 2020 in dl.years

    def test_start_year_none_does_not_filter(self, base_args: dict) -> None:
        """When start_year=None, no year filtering is applied."""
        base_args["years"] = [1800, 2020]
        dl = _ConcreteDownloader(**base_args, start_year=None)
        assert 1800 in dl.years

    def test_empty_checkpoint_on_fresh_start(self, base_args: dict) -> None:
        """Checkpoint is empty dict when resume=False and no file exists."""
        dl = _ConcreteDownloader(**base_args)
        assert dl.checkpoint == {}

    def test_checkpoint_loaded_on_resume(self, tmp_path: Path, base_args: dict) -> None:
        """Existing checkpoint is loaded when resume=True."""
        saved = {(2020, "01", "var_a"): 1}
        checkpoint_path = Path(tmp_path, "status.pickle")
        with open(checkpoint_path, "wb") as f:
            pickle.dump(saved, f)

        base_args["resume"] = True
        dl = _ConcreteDownloader(**base_args)
        assert dl.checkpoint == saved

    def test_checkpoint_ignored_when_resume_false(
        self, tmp_path: Path, base_args: dict
    ) -> None:
        """Existing checkpoint file is ignored when resume=False."""
        saved = {(2020, "01", "var_a"): 1}
        checkpoint_path = Path(tmp_path, "status.pickle")
        with open(checkpoint_path, "wb") as f:
            pickle.dump(saved, f)

        dl = _ConcreteDownloader(**base_args)  # resume=False
        assert dl.checkpoint == {}

    def test_corrupted_checkpoint_starts_fresh(
        self, tmp_path: Path, base_args: dict
    ) -> None:
        """Corrupted checkpoint file is discarded and a fresh checkpoint is returned."""
        checkpoint_path = Path(tmp_path, "status.pickle")
        checkpoint_path.write_bytes(b"not-valid-pickle-data")

        base_args["resume"] = True
        dl = _ConcreteDownloader(**base_args)
        assert dl.checkpoint == {}


# ----------------------------------
# WeatherDownloader._save_checkpoint
# ----------------------------------
class TestSaveCheckpoint:
    """Tests for WeatherDownloader._save_checkpoint.

    Verifies that the checkpoint is written to disk and that no temporary
    artefacts are left behind after a successful save.
    """

    def test_writes_checkpoint_to_disk(self, base_args: dict) -> None:
        """Checkpoint is persisted to disk after _save_checkpoint."""
        dl = _ConcreteDownloader(**base_args)
        dl.checkpoint[(2020, "01", "var_a")] = 1
        dl._save_checkpoint()

        with open(dl.checkpoint_path, "rb") as f:
            loaded = pickle.load(f)
        assert loaded == {(2020, "01", "var_a"): 1}

    def test_atomic_write_no_tmp_left_behind(self, base_args: dict) -> None:
        """Temporary .tmp file is removed after a successful save."""
        dl = _ConcreteDownloader(**base_args)
        dl._save_checkpoint()
        assert not dl.checkpoint_path.with_suffix(".tmp").exists()


# ----------------------------------
# # WeatherDownloader.download_data
# ----------------------------------
class TestDownloadData:
    """Tests for WeatherDownloader.download_data.

    Covers task iteration, checkpoint skipping on resume, checkpoint persistence
    after each task, failure recording, and dry-run behaviour.
    """

    def test_calls_download_task_for_each_task(self, base_args: dict) -> None:
        """_download_task is called once per task returned by _get_tasks."""
        tasks = [(2020, "01", "var_a"), (2020, "02", "var_a")]
        dl = _ConcreteDownloader(tasks=tasks, **base_args)

        with patch.object(dl, "_download_task", return_value=1) as mock_dl:
            dl.download_data()

        assert mock_dl.call_count == 2

    def test_skips_already_completed_tasks(self, base_args: dict) -> None:
        """Tasks already marked 1 in checkpoint are skipped."""
        task = (2020, "01", "var_a")
        base_args["resume"] = True
        dl = _ConcreteDownloader(tasks=[task], **base_args)
        dl.checkpoint[task] = 1

        with patch.object(dl, "_download_task", return_value=1) as mock_dl:
            dl.download_data()

        mock_dl.assert_not_called()

    def test_checkpoint_updated_after_each_task(self, base_args: dict) -> None:
        """Checkpoint is saved after each successful task."""
        task = (2020, "01", "var_a")
        dl = _ConcreteDownloader(tasks=[task], **base_args)

        with patch.object(dl, "_save_checkpoint") as mock_save:
            dl.download_data()

        mock_save.assert_called_once()
        assert dl.checkpoint[task] == 1

    def test_failed_task_recorded_in_checkpoint(self, base_args: dict) -> None:
        """A task returning 0 is recorded as failed (0) in the checkpoint."""
        task = (2020, "01", "var_a")
        dl = _ConcreteDownloader(tasks=[task], **base_args)
        dl._download_results[task] = 0

        dl.download_data()

        assert dl.checkpoint[task] == 0

    def test_dry_run_does_not_update_checkpoint(self, base_args: dict) -> None:
        """Checkpoint is not written during a dry run."""
        base_args["dry_run"] = True
        task = (2020, "01", "var_a")
        dl = _ConcreteDownloader(tasks=[task], **base_args)

        with patch.object(dl, "_save_checkpoint") as mock_save:
            dl.download_data()

        mock_save.assert_not_called()
        assert task not in dl.checkpoint

    def test_no_tasks_completes_without_error(self, base_args: dict) -> None:
        """download_data completes cleanly when there are no tasks."""
        dl = _ConcreteDownloader(tasks=[], **base_args)
        dl.download_data()  # should not raise


# ----------------------------------
# WeatherDownloader — ABC enforcement
# ----------------------------------
class TestAbstractMethods:
    """Tests for WeatherDownloader ABC enforcement.

    Verifies that the abstract base class cannot be instantiated directly and
    that subclasses missing any abstract method raise TypeError.
    """

    def test_cannot_instantiate_abc_directly(self) -> None:
        """WeatherDownloader itself cannot be instantiated (abstract)."""
        with pytest.raises(TypeError):
            WeatherDownloader(  # type: ignore[abstract]
                output_path=Path("/tmp"),
                years=[2020],
                months=None,
                variables=[],
                dry_run=False,
                resume=False,
            )

    def test_subclass_missing_abstract_method_raises(self) -> None:
        """A subclass that omits an abstract method cannot be instantiated."""

        class Incomplete(WeatherDownloader):
            def _get_tasks(self) -> list[tuple]:
                return []

            def _download_task(self, task: tuple) -> int:
                return 1

            # _validate_variables intentionally omitted

        with pytest.raises(TypeError):
            Incomplete(  # type: ignore[abstract]
                output_path=Path("/tmp"),
                years=[2020],
                months=None,
                variables=[],
                dry_run=False,
                resume=False,
            )


# ----------------------------------
# download_file_streaming
# ----------------------------------
class TestDownloadFileStreaming:
    """Tests for download_file_streaming.

    Covers successful file downloads, parent-directory creation, HTTP error
    handling, partial-file cleanup on failure, and network exception handling.
    """

    def test_successful_download_returns_1(self, tmp_path: Path) -> None:
        """Returns 1 and writes file content on a successful download."""
        output_file = Path(tmp_path, "output.nc")
        mock_response = MagicMock()
        mock_response.headers = {"content-length": "5"}
        mock_response.iter_content.return_value = iter([b"hello"])

        with patch("rbc.weather.utils.requests.get", return_value=mock_response):
            result = download_file_streaming(
                url="http://example.com/file.nc",
                output_file=output_file,
                description="test",
            )

        assert result == 1
        assert output_file.read_bytes() == b"hello"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Parent directories of output_file are created if missing."""
        output_file = Path(tmp_path, "deep", "nested", "file.nc")
        mock_response = MagicMock()
        mock_response.headers = {"content-length": "0"}
        mock_response.iter_content.return_value = iter([])

        with patch("rbc.weather.utils.requests.get", return_value=mock_response):
            download_file_streaming("http://example.com/file.nc", output_file, "test")

        assert output_file.parent.is_dir()

    def test_request_exception_returns_0(self, tmp_path: Path) -> None:
        """Returns 0 when a requests.RequestException is raised."""
        output_file = Path(tmp_path, "output.nc")

        with patch(
            "rbc.weather.utils.requests.get",
            side_effect=requests.exceptions.RequestException("network error"),
        ):
            result = download_file_streaming(
                "http://example.com/file.nc", output_file, "test"
            )

        assert result == 0

    def test_partial_file_cleaned_up_on_failure(self, tmp_path: Path) -> None:
        """Partial output file is deleted after a download failure."""
        output_file = Path(tmp_path, "output.nc")

        mock_response = MagicMock()
        mock_response.headers = {"content-length": "100"}
        mock_response.iter_content.side_effect = Exception("mid-stream failure")

        with patch("rbc.weather.utils.requests.get", return_value=mock_response):
            result = download_file_streaming(
                "http://example.com/file.nc", output_file, "test"
            )

        assert result == 0
        assert not output_file.exists()

    def test_http_error_returns_0(self, tmp_path: Path) -> None:
        """Returns 0 when the server returns a 4xx/5xx response."""
        output_file = Path(tmp_path, "output.nc")

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404"
        )

        with patch("rbc.weather.utils.requests.get", return_value=mock_response):
            result = download_file_streaming(
                "http://example.com/file.nc", output_file, "test"
            )

        assert result == 0
