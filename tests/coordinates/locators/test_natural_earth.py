# tests/coordinates/locators/test_natural_earth.py
"""Tests for the RegionRegistry's classification, caching and resource handling."""

from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pytest
from shapely.geometry import box
from shapely.prepared import prep

from rbc.coordinates.locators.natural_earth import (
    NE_ADMIN1_FILE,
    NE_ADMIN1_ZIP_URL,
    RegionRegistry,
)

NE_MODULE = "rbc.coordinates.locators.natural_earth"


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def admin1_gdf() -> gpd.GeoDataFrame:
    """Stand-in for the Natural Earth admin-1 data: one country with two regions.

    "Testshire" is a 1°x1° box (ca. 110km x 70km at this latitude), so a point a few
    tenths of a degree outside it still falls within the 20km buffer.

    Returns:
        gpd.GeoDataFrame: Minimal admin-1 frame with the columns the registry reads.
    """
    return gpd.GeoDataFrame(
        [
            {
                "admin": "Testland",
                "name": "Testshire",
                "name_en": "Testshire",
                "name_alt": "Teszt|Testshire Province",
                "geometry": box(10.0, 50.0, 11.0, 51.0),
            },
            {
                "admin": "Testland",
                "name": "Farshire",
                "name_en": "Farshire",
                "name_alt": None,
                "geometry": box(20.0, 40.0, 21.0, 41.0),
            },
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )


# ----------------------------------
# Tests - RegionRegistry (classification)
# ----------------------------------
class TestClassifyMatch:
    """Tests for RegionRegistry.classify_match."""

    @pytest.mark.parametrize(
        "region, coord, expected",
        [
            ("Testshire", (50.5, 10.5), "within_borders"),  # well inside
            ("Testshire", (50.5, 11.1), "within_bounds"),  # ca. 7km east of the border
            ("Testshire", (40.5, 20.5), "mismatch"),  # inside the other region
            ("Teszt", (50.5, 10.5), "within_borders"),  # "name_alt" alias
            ("Nowhereshire", (50.5, 10.5), "unknown"),  # unresolvable name
            (None, (50.5, 10.5), "unknown"),  # no region info given
            ("", (50.5, 10.5), "unknown"),  # no region info given
        ],
    )
    def test_position_relative_to_region(
        self,
        admin1_gdf: gpd.GeoDataFrame,
        region: str | None,
        coord: tuple[float, float],
        expected: str,
    ) -> None:
        """Happy path: a coordinate is classified by its position in the named region.

        Args:
            admin1_gdf (gpd.GeoDataFrame): Stand-in admin-1 frame.
            region (str | None): The target's region name.
            coord (tuple[float, float]): The candidate coordinate (lat, lon).
            expected (str): The expected classification.
        """
        with patch(f"{NE_MODULE}.gpd.read_file", return_value=admin1_gdf):
            assert (
                RegionRegistry().classify_match("Testland", region, coord) == expected
            )

    def test_unknown_country_never_vetoes(self, admin1_gdf: gpd.GeoDataFrame) -> None:
        """Failure path: a country with no admin-1 regions disables the check.

        Args:
            admin1_gdf (gpd.GeoDataFrame): Stand-in frame (holds no "Absurdistan").
        """
        with patch(f"{NE_MODULE}.gpd.read_file", return_value=admin1_gdf):
            registry = RegionRegistry()
            assert registry.classify_match(
                "Absurdistan", "Testshire", (50.5, 10.5)
            ) == ("unknown")


# ----------------------------------
# Tests - RegionRegistry (caching)
# ----------------------------------
class TestRegionRegistryCaching:
    """Tests for the instance-level caches (admin-1 data and per-country polygons)."""

    def test_data_is_read_once_per_instance(self, admin1_gdf: gpd.GeoDataFrame) -> None:
        """Happy path: repeated checks reuse the admin-1 data and prepared polygons.

        The country's polygons are prepared (and buffered) exactly once — two per
        region, strict and buffered — no matter how many EGEs are checked against them.

        Args:
            admin1_gdf (gpd.GeoDataFrame): Stand-in admin-1 frame.
        """
        with (
            patch(f"{NE_MODULE}.gpd.read_file", return_value=admin1_gdf) as mock_read,
            patch(f"{NE_MODULE}.prep", side_effect=prep) as mock_prep,
        ):
            registry = RegionRegistry()
            for _ in range(3):
                registry.classify_match("Testland", "Testshire", (50.5, 10.5))
            registry.classify_match("Absurdistan", "Testshire", (50.5, 10.5))

        mock_read.assert_called_once()
        assert mock_prep.call_count == 4  # 2 regions x (strict, buffered)

    def test_nothing_is_read_without_a_region(
        self, admin1_gdf: gpd.GeoDataFrame
    ) -> None:
        """Happy path: with no region to check against, the data is never read.

        Most operators give no region at all, so their runs must not pay for the
        ca. 15MB admin-1 download.

        Args:
            admin1_gdf (gpd.GeoDataFrame): Stand-in admin-1 frame.
        """
        with (
            patch(f"{NE_MODULE}.fetch_resource") as mock_fetch,
            patch(f"{NE_MODULE}.gpd.read_file", return_value=admin1_gdf) as mock_read,
        ):
            assert RegionRegistry().classify_match("Testland", None, (50.5, 10.5)) == (
                "unknown"
            )

        mock_fetch.assert_not_called()
        mock_read.assert_not_called()


# ----------------------------------
# Tests - RegionRegistry (resource handling)
# ----------------------------------
class TestRegionRegistryResource:
    """Tests for where RegionRegistry reads the Natural Earth admin-1 data from."""

    def test_cache_dir_is_used_as_local_copy(self, tmp_path: Path) -> None:
        """Happy path: the admin-1 zip is read from the given cache dir.

        Args:
            tmp_path (Path): Pytest-provided temporary directory (cache dir).
        """
        local = Path(tmp_path, NE_ADMIN1_FILE)

        with (
            patch(f"{NE_MODULE}.fetch_resource", return_value=local) as mock_fetch,
            patch(
                f"{NE_MODULE}.gpd.read_file", return_value=gpd.GeoDataFrame()
            ) as mock_read,
        ):
            RegionRegistry(cache_dir=tmp_path, update=True)._get_admin1_df()

        mock_fetch.assert_called_once_with(NE_ADMIN1_ZIP_URL, local, True)
        assert mock_read.call_args.args[0] == local

    def test_without_cache_dir_the_url_is_read(self) -> None:
        """Happy path: with no cache dir, the data is read straight from its URL."""
        with (
            patch(f"{NE_MODULE}.fetch_resource") as mock_fetch,
            patch(
                f"{NE_MODULE}.gpd.read_file", return_value=gpd.GeoDataFrame()
            ) as mock_read,
        ):
            RegionRegistry()._get_admin1_df()

        mock_fetch.assert_not_called()
        assert mock_read.call_args.args[0] == NE_ADMIN1_ZIP_URL

    def test_failed_download_falls_back_to_url(self, tmp_path: Path) -> None:
        """Failure path: if no local copy can be had, the data is read from its URL.

        Args:
            tmp_path (Path): Pytest-provided temporary directory (cache dir).
        """
        with (
            patch(f"{NE_MODULE}.fetch_resource", return_value=None),
            patch(
                f"{NE_MODULE}.gpd.read_file", return_value=gpd.GeoDataFrame()
            ) as mock_read,
        ):
            RegionRegistry(cache_dir=tmp_path)._get_admin1_df()

        assert mock_read.call_args.args[0] == NE_ADMIN1_ZIP_URL
