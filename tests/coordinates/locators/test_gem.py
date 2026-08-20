# tests/coordinates/locators/test_gem.py
"""Tests for the GEM locator's file resolution, remote fallback and caching."""

from pathlib import Path
from typing import Callable
from unittest.mock import patch

import pandas as pd
import pytest
import requests

from rbc.coordinates.locators.gem import _TRACKER_SPECS, GEMLocator

# Stand-ins for the xlsx URLs PPM's config lists (including non-GEM URL)
FAKE_URLS = [
    "https://ppm.example/Kraftwerksliste_2019_1.xlsx",  # not a GEM tracker
    "https://ppm.example/Global-Coal-Plant-Tracker-July-2025.xlsx",
    "https://ppm.example/Global-Oil-and-Gas-Plant-Tracker-GOGPT-August-2025.xlsx",
    "https://ppm.example/Global-Wind-Power-Tracker-February-2026.xlsx",
    "https://ppm.example/Global-Solar-Power-Tracker-February-2026.xlsx",
    "https://ppm.example/Global-Hydropower-Tracker-April-2025.xlsx",
    "https://ppm.example/Global-Nuclear-Power-Tracker-July-2024.xlsx",
    "https://ppm.example/Global-Bioenergy-Power-Tracker-GBPT-V3.xlsx",
    "https://ppm.example/Geothermal-Power-Tracker-March-2025-Final.xlsx",
]


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def get_locator() -> Callable[..., GEMLocator]:
    """Factory for a GEMLocator with __init__ skipped and only gem_dir, so no files are read.

    Returns:
        Callable[..., GEMLocator]: Factory taking an optional `gem_dir`.
    """

    def _factory(gem_dir: Path | None = None) -> GEMLocator:
        """Build a GEMLocator without running __init__.

        Args:
            gem_dir (Path | None): Directory to resolve local tracker files from.

        Returns:
            GEMLocator: Instance with only `gem_dir` set.
        """
        locator = GEMLocator.__new__(GEMLocator)
        locator.gem_dir = gem_dir
        return locator

    return _factory


# ----------------------------------
# Tests - GemLocator (loading & caching)
# ----------------------------------
class TestGemLocatorLoad:
    """Tests for GEMLocator._load."""

    def test_cache_is_used(self, tmp_path: Path) -> None:
        """Happy path: An existing parquet is reused, so remote trackers are never fetched.

        Remote sources have no mtime, so the check treats any existing cache as current
        (keeps a fallback run from re-fetching ~32MB of files).

        Args:
            tmp_path (Path): Pytest-provided temporary directory, used as `cache_dir`.
        """
        cached = pd.DataFrame([{"plant_name": "Cached Plant", "lat": 1.0, "lon": 2.0}])
        cached.to_parquet(Path(tmp_path, "gem_combined.parquet"), index=False)

        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=FAKE_URLS):
            locator = GEMLocator(gem_dir=None, cache_dir=tmp_path)
            print(locator.df)
            assert list(locator.df["plant_name"]) == ["Cached Plant"]

    def test_no_sources_returns_empty_df(self, tmp_path: Path) -> None:
        """Failure path: No local files and no fallback returns an empty, usable locator.

        Args:
            tmp_path (Path): Temporary directory (used as empty `gem_dir`).
        """
        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=[]):
            locator = GEMLocator(gem_dir=tmp_path)
            assert locator.df.empty
            assert locator.match_by_entsoe_id("11W-ANY") is None

    def test_unreadable_file_is_skipped(self, tmp_path: Path) -> None:
        """Failure path: A corrupt tracker file is skipped (error is not raised).

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir).
        """
        Path(tmp_path, "Global-Coal-Plant-Tracker-2026-01.xlsx").write_text("not xlsx")
        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=[]):
            assert GEMLocator(gem_dir=tmp_path).df.empty


# ----------------------------------
# Tests - GemLocator (helper methods)
# ----------------------------------
class TestGemLocatorXlsxFiles:
    """Tests for setup/loading helpers (_resolve_gem_xlsx_files)."""

    def test_fallback_when_no_gem_dir(self, get_locator: Callable) -> None:
        """Happy path: No gem_dir -> every tracker resolves to remote URL (non-GEM ignored).

        Args:
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=FAKE_URLS):
            resolved = get_locator(None)._resolve_gem_xlsx_files()

            assert set(resolved) == set(_TRACKER_SPECS)
            assert all(isinstance(v, str) for v in resolved.values())
            assert not any("Kraftwerksliste" in v for v in resolved.values())

    def test_local_over_fallback(self, tmp_path: Path, get_locator: Callable) -> None:
        """Happy path: A tracker in gem_dir is used before the remote fallback URL.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir).
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        local = Path(tmp_path, "Global-Coal-Plant-Tracker-2026-01.xlsx")
        local.touch()

        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=FAKE_URLS):
            resolved = get_locator(tmp_path)._resolve_gem_xlsx_files()
            assert resolved["coal"] == local

    def test_fallback_per_tracker(self, tmp_path: Path, get_locator: Callable) -> None:
        """Happy path: Trackers missing locally fall back individually, not all-or-nothing.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir).
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        Path(tmp_path, "Global-Coal-Plant-Tracker-2026-01.xlsx").touch()

        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=FAKE_URLS):
            resolved = get_locator(tmp_path)._resolve_gem_xlsx_files()
            assert isinstance(resolved["coal"], Path)  # found locally
            assert isinstance(resolved["wind"], str)  # from remote tracker

    def test_newest_local_wins(self, tmp_path: Path, get_locator: Callable) -> None:
        """Happy path: If several versions of one tracker exist, the newest is chosen.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir).
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        import os

        older = Path(tmp_path, "Global-Coal-Plant-Tracker-2024-01.xlsx")
        newer = Path(tmp_path, "Global-Coal-Plant-Tracker-2026-01.xlsx")
        older.touch()
        newer.touch()

        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=[]):
            os.utime(older, (1, 1))  # force an older mtime
            assert get_locator(tmp_path)._resolve_gem_xlsx_files()["coal"] == newer

    def test_no_sources_resolves_empty(
        self, tmp_path: Path, get_locator: Callable
    ) -> None:
        """Failure path: An empty gem_dir and no fallback means no files and GEM locator.

        Args:
            tmp_path (Path): Pytest-provided empty temporary directory.
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=[]):
            assert get_locator(tmp_path)._resolve_gem_xlsx_files() == {}


# ----------------------------------
# Tests - GemLocator (cached properties)
# ----------------------------------
class TestGemLocatorCachedProperties:
    """Tests for cached properties (_fallback_xlsx_urls)."""

    def test_fallback_urls_unreachable_is_empty(self, get_locator: Callable) -> None:
        """Failure path: An unreachable PPM config returns no URLs (does not raise an error).

        Args:
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        with patch(
            "rbc.coordinates.locators.gem.requests.get",
            side_effect=requests.RequestException("no route to host"),
        ):
            assert get_locator(None)._fallback_xlsx_urls == []
