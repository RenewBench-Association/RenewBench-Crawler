# tests/coordinates/utils/test_resources.py
"""Tests for the local storage of downloaded resource files."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from rbc.coordinates.locators.eic_registry import EIC_CSV_FILE, EIC_CSV_URL
from rbc.coordinates.locators.natural_earth import NE_ADMIN1_FILE, NE_ADMIN1_ZIP_URL
from rbc.coordinates.locators.osmpp import OSMPP_CSV_FILE, OSMPP_CSV_URL
from rbc.coordinates.locators.ppm import PPM_CSV_FILE, PPM_CSV_URL
from rbc.coordinates.utils.resources import fetch_resource

URL = "https://example.invalid/resource.csv"

# Every resource's (composed) download URL and the local file name it is stored under
RESOURCE_URLS = [
    pytest.param(EIC_CSV_URL, EIC_CSV_FILE, id="eic"),
    pytest.param(NE_ADMIN1_ZIP_URL, NE_ADMIN1_FILE, id="natural_earth"),
    pytest.param(OSMPP_CSV_URL, OSMPP_CSV_FILE, id="osmpp"),
    pytest.param(PPM_CSV_URL, PPM_CSV_FILE, id="ppm"),
]


# ----------------------------------
# Fixtures
# ----------------------------------
def _download(content: bytes = b"fresh") -> MagicMock:
    """Build a stand-in for a streamed `requests.get` response with the given content.

    Args:
        content (bytes, optional): Content the response streams. Defaults to b"fresh".

    Returns:
        MagicMock: Response double usable as a context manager.
    """
    response = MagicMock()
    response.iter_content.return_value = [content]
    response.__enter__.return_value = response
    return response


# ----------------------------------
# Tests
# ----------------------------------
class TestFetchResource:
    """Tests for fetch_resource."""

    def test_existing_file_is_not_downloaded(self, tmp_path: Path) -> None:
        """Happy path: an existing local file is used without asking the network.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        file_path = Path(tmp_path, "resource.csv")
        file_path.write_bytes(b"local")

        with patch("rbc.coordinates.utils.resources.requests.get") as mock_get:
            result = fetch_resource(URL, file_path)

        assert result == file_path
        assert file_path.read_bytes() == b"local"
        mock_get.assert_not_called()

    def test_missing_file_is_downloaded_and_stored(self, tmp_path: Path) -> None:
        """Happy path: a missing file is downloaded, stored and left behind for reuse.

        The subfolder is created on the way, so a resources dir needs no preparation.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        file_path = Path(tmp_path, "ppm", "resource.csv")

        with patch(
            "rbc.coordinates.utils.resources.requests.get", return_value=_download()
        ) as mock_get:
            result = fetch_resource(URL, file_path)

        assert result == file_path
        assert file_path.read_bytes() == b"fresh"
        assert mock_get.call_args.args[0] == URL

    def test_update_replaces_existing_file(self, tmp_path: Path) -> None:
        """Happy path: update mode downloads again and overwrites the local file.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        file_path = Path(tmp_path, "resource.csv")
        file_path.write_bytes(b"local")

        with patch(
            "rbc.coordinates.utils.resources.requests.get", return_value=_download()
        ):
            result = fetch_resource(URL, file_path, update=True)

        assert result == file_path
        assert file_path.read_bytes() == b"fresh"

    def test_failed_download_keeps_using_local_file(self, tmp_path: Path) -> None:
        """Failure path: an existing file is kept when a fresh download fails.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        file_path = Path(tmp_path, "resource.csv")
        file_path.write_bytes(b"local")

        with patch(
            "rbc.coordinates.utils.resources.requests.get",
            side_effect=requests.RequestException("no route to host"),
        ):
            result = fetch_resource(URL, file_path, update=True)

        assert result == file_path
        assert file_path.read_bytes() == b"local"

    def test_failed_download_without_local_file_returns_none(
        self, tmp_path: Path
    ) -> None:
        """Failure path: without a local file, a failed download returns None.

        No half-written file is left behind either, so the next run doesn't read a
        truncated file as if it were complete.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
        """
        file_path = Path(tmp_path, "resource.csv")

        with patch(
            "rbc.coordinates.utils.resources.requests.get",
            side_effect=requests.RequestException("no route to host"),
        ):
            result = fetch_resource(URL, file_path)

        assert result is None
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize("update", [False, True])
    def test_interrupted_download_leaves_no_file(
        self, tmp_path: Path, update: bool
    ) -> None:
        """Failure path: a download that dies mid-stream leaves no partial file.

        Args:
            tmp_path (Path): Pytest-provided temporary directory.
            update (bool): Whether the fetch was asked for a fresh copy.
        """
        file_path = Path(tmp_path, "resource.csv")
        response = _download()
        response.iter_content.side_effect = requests.ConnectionError("reset by peer")

        with patch(
            "rbc.coordinates.utils.resources.requests.get", return_value=response
        ):
            result = fetch_resource(URL, file_path, update=update)

        assert result is None
        assert list(tmp_path.iterdir()) == []


# ----------------------------------
# Tests - resource URLs
# ----------------------------------
@pytest.mark.parametrize("url, file_name", RESOURCE_URLS)
def test_url_points_at_the_file(url: str, file_name: str) -> None:
    """Happy path: a resource's URL addresses its file, not the folder it sits in.

    Each URL is composed from a base and the file name it is stored under, so the two
    can drift apart. A base URL in its place need not even fail: Natural Earth's answers
    200 with an empty body, so a 0-byte file would be stored and reused from then on.

    Args:
        url (str): The resource's composed download URL.
        file_name (str): The name the resource is stored under locally.
    """
    assert url.endswith(f"/{file_name}")
