# tests/coordinates/locators/test_gem.py
"""Tests for the GEM locator's file resolution, remote fallback and caching."""

import os
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import pandas as pd
import pytest
import requests

from rbc.coordinates.locators.gem import _TRACKER_SPECS, GEMLocator

GEM_MODULE = "rbc.coordinates.locators.gem"


def _fake_download(url: str, file_path: Path, update: bool = False) -> Path:
    """Stand in for `fetch_resource`: pretend `url` was downloaded to `file_path`.

    Args:
        url (str): URL the caller wanted to download.
        file_path (Path): Path the local copy should be written to.
        update (bool, optional): Ignored, as nothing is really downloaded.

    Returns:
        Path: Path of the (empty) local copy.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.touch()
    return file_path


def _make_cache(cache_dir: Path) -> Path:
    """Write a combined-data parquet cache holding one recognizable plant.

    Args:
        cache_dir (Path): Directory to write the parquet into.

    Returns:
        Path: Path of the written parquet cache.
    """
    cache_path = Path(cache_dir, "gem_combined.parquet")
    cached = pd.DataFrame([{"plant_name": "Cached Plant", "lat": 1.0, "lon": 2.0}])
    cached.to_parquet(cache_path, index=False)
    return cache_path


def _fake_rebuild(tracker_files: dict[str, Path | str]) -> pd.DataFrame:
    """Stand in for `_normalize_xlsx_into_df`: pretend the trackers parsed fine.

    Args:
        tracker_files (dict[str, Path | str]): Resolved trackers (ignored).

    Returns:
        pd.DataFrame: Frame with one plant, distinguishable from the cached one.
    """
    return pd.DataFrame([{"plant_name": "Rebuilt Plant", "lat": 3.0, "lon": 4.0}])


def _resolve(locator: GEMLocator) -> dict[str, Path | str]:
    """Resolve a locator's trackers the way `_load` does: local first, then remote.

    Args:
        locator (GEMLocator): The locator whose trackers to resolve.

    Returns:
        dict[str, Path | str]: Resolved tracker key -> local path or URL.
    """
    return locator._download_missing_trackers(locator._find_local_trackers())


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
            GEMLocator: Instance with only the tracker-resolving attributes set.
        """
        locator = GEMLocator.__new__(GEMLocator)
        locator.gem_dir = gem_dir
        locator.fallback_dir = Path(gem_dir, "fallback") if gem_dir else None
        locator.update = False
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

    def test_cache_is_used_without_resolving_remote_trackers(
        self, tmp_path: Path
    ) -> None:
        """Happy path: With a cache and no local trackers, nothing remote is resolved.

        The cache is checked before any download, so a cached run needs no network.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir and cache_dir).
        """
        cached = pd.DataFrame([{"plant_name": "Cached Plant", "lat": 1.0, "lon": 2.0}])
        cached.to_parquet(Path(tmp_path, "gem_combined.parquet"), index=False)

        with (
            patch.object(GEMLocator, "_fallback_xlsx_urls", new=FAKE_URLS),
            patch(f"{GEM_MODULE}.fetch_resource") as mock_fetch,
        ):
            locator = GEMLocator(gem_dir=tmp_path)

        assert list(locator.df["plant_name"]) == ["Cached Plant"]
        mock_fetch.assert_not_called()

    def test_update_bypasses_the_cache(self, tmp_path: Path) -> None:
        """Happy path: `-u` rebuilds from the trackers instead of reading the parquet.

        The tracker file is deliberately older than the cache, so only `-u` can be the
        reason the cache was skipped.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir and cache_dir).
        """
        _make_cache(tmp_path)
        Path(tmp_path, "Global-Coal-Plant-Tracker-2024-01.xlsx").touch()
        os.utime(Path(tmp_path, "Global-Coal-Plant-Tracker-2024-01.xlsx"), (1, 1))

        with (
            patch.object(GEMLocator, "_fallback_xlsx_urls", new=[]),
            patch.object(
                GEMLocator, "_normalize_xlsx_into_df", new=staticmethod(_fake_rebuild)
            ),
        ):
            locator = GEMLocator(gem_dir=tmp_path, update=True)

        assert list(locator.df["plant_name"]) == ["Rebuilt Plant"]

    def test_newer_tracker_invalidates_the_cache(self, tmp_path: Path) -> None:
        """Happy path: A tracker file newer than the parquet forces a rebuild.

        Dropping a freshly downloaded tracker into the folder has to take effect on the
        next run, rather than being masked by the cache built from the older files.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir and cache_dir).
        """
        cache_path = _make_cache(tmp_path)

        newer = Path(tmp_path, "Global-Coal-Plant-Tracker-2026-01.xlsx")
        newer.touch()
        future = cache_path.stat().st_mtime + 10
        os.utime(newer, (future, future))

        with (
            patch.object(GEMLocator, "_fallback_xlsx_urls", new=[]),
            patch.object(
                GEMLocator, "_normalize_xlsx_into_df", new=staticmethod(_fake_rebuild)
            ),
        ):
            locator = GEMLocator(gem_dir=tmp_path)

        assert list(locator.df["plant_name"]) == ["Rebuilt Plant"]

    def test_unparseable_trackers_fall_back_to_the_cache(self, tmp_path: Path) -> None:
        """Failure path: If a rebuild extracts nothing, the existing cache is used.

        GEM has renamed tracker sheets before, and a download can arrive corrupt. Either
        way the run keeps the coordinates it had rather than losing GEM altogether.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir and cache_dir).
        """
        cache_path = _make_cache(tmp_path)

        newer = Path(tmp_path, "Global-Coal-Plant-Tracker-2026-01.xlsx")
        newer.write_text("not xlsx")  # unreadable, so the rebuild extracts nothing
        future = cache_path.stat().st_mtime + 10
        os.utime(newer, (future, future))

        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=[]):
            locator = GEMLocator(gem_dir=tmp_path)

        assert list(locator.df["plant_name"]) == ["Cached Plant"]

    def test_failed_update_falls_back_to_the_cache(self, tmp_path: Path) -> None:
        """Failure path: A `-u` run that can resolve no tracker at all keeps the cache.

        Offline with no manually downloaded trackers, `-u` cannot refresh anything —
        which must not cost the run its existing GEM data.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir and cache_dir).
        """
        _make_cache(tmp_path)

        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=[]):
            locator = GEMLocator(gem_dir=tmp_path, update=True)

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
    """Tests for the tracker-resolving helpers (local files, then remote fallback)."""

    def test_fallback_when_no_gem_dir(self, get_locator: Callable) -> None:
        """Happy path: No gem_dir -> every tracker resolves to remote URL (non-GEM ignored).

        Args:
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=FAKE_URLS):
            resolved = _resolve(get_locator(None))

            assert set(resolved) == set(_TRACKER_SPECS)
            assert all(isinstance(v, str) for v in resolved.values())
            assert not any("Kraftwerksliste" in str(v) for v in resolved.values())

    def test_local_over_fallback(self, tmp_path: Path, get_locator: Callable) -> None:
        """Happy path: A tracker in gem_dir is used before the remote fallback URL.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir).
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        local = Path(tmp_path, "Global-Coal-Plant-Tracker-2026-01.xlsx")
        local.touch()

        with (
            patch.object(GEMLocator, "_fallback_xlsx_urls", new=FAKE_URLS),
            patch(f"{GEM_MODULE}.fetch_resource", side_effect=_fake_download),
        ):
            resolved = _resolve(get_locator(tmp_path))
            assert resolved["coal"] == local

    def test_manual_file_beats_downloaded_fallback(
        self, tmp_path: Path, get_locator: Callable
    ) -> None:
        """Happy path: A manually downloaded tracker wins over a newer fallback copy.

        Fallback copies live in `gem_dir/fallback/`, and a re-downloaded (older) version
        must not displace the manual file just by having a newer file date.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir).
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        manual = Path(tmp_path, "Global-Coal-Plant-Tracker-2024-01.xlsx")
        manual.touch()
        os.utime(manual, (1, 1))  # force an older mtime than the fallback copy

        fallback = Path(tmp_path, "fallback", "Global-Coal-Plant-Tracker-2026-01.xlsx")
        fallback.parent.mkdir()
        fallback.touch()

        assert get_locator(tmp_path)._find_local_trackers()["coal"] == manual

    def test_downloaded_fallback_counts_as_a_local_file(
        self, tmp_path: Path, get_locator: Callable
    ) -> None:
        """Happy path: With no manual file, the copy in `fallback/` is the local file.

        Keeps a re-downloaded tracker visible to the cache check, so its file date can
        invalidate the combined parquet (s. `_load`).

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir).
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        fallback = Path(tmp_path, "fallback", "Global-Coal-Plant-Tracker-2026-01.xlsx")
        fallback.parent.mkdir()
        fallback.touch()

        assert get_locator(tmp_path)._find_local_trackers()["coal"] == fallback

    def test_update_refetches_an_existing_fallback_copy(
        self, tmp_path: Path, get_locator: Callable
    ) -> None:
        """Happy path: `-u` fetches fallback trackers again instead of reusing the copy.

        A tracker with no manually downloaded file is only ever as current as the last
        fallback download, so `-u` has to reach past `fallback/` to refresh it.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir).
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        stale = Path(tmp_path, "fallback", "Global-Coal-Plant-Tracker-July-2025.xlsx")
        stale.parent.mkdir()
        stale.touch()

        locator = get_locator(tmp_path)
        locator.update = True

        with (
            patch.object(GEMLocator, "_fallback_xlsx_urls", new=FAKE_URLS),
            patch(
                f"{GEM_MODULE}.fetch_resource", side_effect=_fake_download
            ) as mock_fetch,
        ):
            resolved = _resolve(locator)

        assert resolved["coal"] == stale  # same path, but re-downloaded into it
        coal_calls = [c for c in mock_fetch.call_args_list if c.args[1] == stale]
        assert len(coal_calls) == 1  # the existing copy did not short-circuit the fetch
        assert coal_calls[0].args[2] is True  # update passed on

    def test_fallback_is_downloaded_into_fallback_dir(
        self, tmp_path: Path, get_locator: Callable
    ) -> None:
        """Happy path: A tracker missing locally is downloaded into `gem_dir/fallback/`.

        Storing it locally means later runs (and runs without a network) find it as a
        local file instead of resolving the remote URL again.

        Args:
            tmp_path (Path): Temporary directory (used as gem_dir).
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        Path(tmp_path, "Global-Coal-Plant-Tracker-2026-01.xlsx").touch()

        with (
            patch.object(GEMLocator, "_fallback_xlsx_urls", new=FAKE_URLS),
            patch(f"{GEM_MODULE}.fetch_resource", side_effect=_fake_download),
        ):
            resolved = _resolve(get_locator(tmp_path))

        assert resolved["coal"] == Path(
            tmp_path, "Global-Coal-Plant-Tracker-2026-01.xlsx"
        )
        assert resolved["wind"] == Path(
            tmp_path, "fallback", "Global-Wind-Power-Tracker-February-2026.xlsx"
        )

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
            assert _resolve(get_locator(tmp_path))["coal"] == newer

    def test_no_sources_resolves_empty(
        self, tmp_path: Path, get_locator: Callable
    ) -> None:
        """Failure path: An empty gem_dir and no fallback means no files and GEM locator.

        Args:
            tmp_path (Path): Pytest-provided empty temporary directory.
            get_locator (Callable): Factory returning a GEMLocator without __init__.
        """
        with patch.object(GEMLocator, "_fallback_xlsx_urls", new=[]):
            assert _resolve(get_locator(tmp_path)) == {}


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
