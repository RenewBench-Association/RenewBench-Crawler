# tests/coordinates/pipelines/test_init.py
"""Tests for the pipelines package's __init__ helpers."""

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from rbc.coordinates import pipelines
from rbc.coordinates.locators.eic_registry import EICCodeRegistry
from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.natural_earth import RegionRegistry
from rbc.coordinates.locators.osm_api import OverpassLocator
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.pipelines import build_shared_resources, make_pipeline
from rbc.coordinates.pipelines.default import DefaultPipeline
from rbc.coordinates.pipelines.entsoe import EntsoePipeline


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def eia_dir(tmp_path: Path) -> Path:
    """A real "eia" operator directory (default pipeline).

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        Path: The EIA CSV directory.
    """
    csv_dir = Path(tmp_path, "eia", "1h")
    csv_dir.mkdir(parents=True)
    return csv_dir


@pytest.fixture
def entsoe_zone_dir(tmp_path: Path) -> Path:
    """A real "entsoe" operator directory (entsoe pipeline).

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        Path: The "entsoe/10YNL----------L" zone directory.
    """
    zone_dir = Path(tmp_path, "entsoe", "10YNL----------L")
    zone_dir.mkdir(parents=True)
    return zone_dir


# ----------------------------------
# Tests: make_pipeline
# ----------------------------------
class TestMakePipeline:
    """Test the 'make_pipeline' function."""

    @pytest.mark.parametrize("eic_reg", [None, object()])
    def test_resolves_default_pipeline(self, eia_dir: Path, eic_reg: Any) -> None:
        """Happy path: any operator other than entsoe resolves to DefaultPipeline.

        Providing an EIC registry should have no effect, as this can't be used by the
        default pipeline.

        Args:
            eia_dir (Path): The synthetic "eia" CSV directory.
            eic_reg (Any): The EIC registry object (if any).
        """
        pipeline = make_pipeline(input_dir=eia_dir, eic_reg=eic_reg)
        assert isinstance(pipeline, DefaultPipeline)

    def test_esolves_entsoe_pipeline(self, entsoe_zone_dir: Path):
        """Happy path: the entsoe operator resolves to EntsoePipeline.

        Args:
            entsoe_zone_dir (Path): The synthetic "entsoe/10YNL----------L" zone directory.
        """
        pipeline = make_pipeline(input_dir=entsoe_zone_dir)
        assert isinstance(pipeline, EntsoePipeline)

    @pytest.mark.parametrize("input_dir_fix", ["eia_dir", "entsoe_zone_dir"])
    def test_use_osm_loc(
        self, input_dir_fix: str, request: pytest.FixtureRequest
    ) -> None:
        """Happy path: both pipelines use the given (shared) Overpass locator.

        If a pipeline built its own locator instead, every directory would load its
        country again, and `--update` would be ignored.

        Args:
            input_dir_fix (str): Name of the directory fixture (default or entsoe).
            request (pytest.FixtureRequest): Pytest-provided request to get the fixture.
        """
        osm_loc = OverpassLocator()
        pipeline = make_pipeline(
            input_dir=request.getfixturevalue(input_dir_fix), osm_loc=osm_loc
        )
        assert pipeline.osm_loc is osm_loc

    @pytest.mark.parametrize("input_dir_fix", ["eia_dir", "entsoe_zone_dir"])
    def test_use_region_reg(
        self, input_dir_fix: str, request: pytest.FixtureRequest
    ) -> None:
        """Happy path: both pipelines use the given (shared) region index.

        If a pipeline built its own index instead, every directory would read the
        admin-1 data again, and `resources_dir` / `--update` would be ignored.

        Args:
            input_dir_fix (str): Name of the directory fixture (default or entsoe).
            request (pytest.FixtureRequest): Pytest-provided request to get the fixture.
        """
        region_reg = RegionRegistry()
        pipeline = make_pipeline(
            input_dir=request.getfixturevalue(input_dir_fix), region_reg=region_reg
        )
        assert pipeline.region_reg is region_reg


class TestBuildSharedResources:
    """Test the 'build_shared_resources' function."""

    def test_default_pipeline(self) -> None:
        """Happy path: default pipeline builds a OSMPP ppdb, a GEM loc but no EIC registry."""
        shared = build_shared_resources(source="eia", resources_dir=None)
        assert isinstance(shared.ppdb_loc, OSMPPLocator)
        assert isinstance(shared.gem_loc, GEMLocator)
        assert isinstance(shared.osm_loc, OverpassLocator)
        assert shared.eic_reg is None

    def test_entsoe_pipeline(self) -> None:
        """Happy path: entsoe pipeline builds a PPM ppdb, a GEM loc and an EIC registry."""
        shared = build_shared_resources(source="entsoe", resources_dir=None)
        assert isinstance(shared.ppdb_loc, PPMLocator)
        assert isinstance(shared.gem_loc, GEMLocator)
        assert isinstance(shared.osm_loc, OverpassLocator)
        assert shared.eic_reg is not None
        assert isinstance(shared.eic_reg, EICCodeRegistry)

    @pytest.mark.parametrize("update", [False, True])
    def test_resources_get_own_subfolders(self, tmp_path: Path, update: bool) -> None:
        """Happy path: each resource gets its own subfolder of `resources_dir`.

        The update flag has to reach every one of them, since `-u` refreshes all
        downloaded resources.

        Args:
            tmp_path (Path): Pytest-provided temporary directory (`resources_dir`).
            update (bool): Whether fresh copies were requested.
        """
        shared = build_shared_resources(
            source="entsoe", resources_dir=tmp_path, update=update
        )

        cast(MagicMock, pipelines.GEMLocator).assert_called_once_with(
            gem_dir=Path(tmp_path, "gem"), update=update
        )
        cast(MagicMock, pipelines.PPMLocator).assert_called_once_with(
            cache_dir=Path(tmp_path, "ppm"), update=update
        )
        cast(MagicMock, pipelines.EICCodeRegistry).assert_called_once_with(
            cache_dir=Path(tmp_path, "eic"), update=update
        )
        assert shared.osm_loc is not None
        assert shared.osm_loc.cache_dir == Path(tmp_path, "overpass")
        assert shared.osm_loc.update is update
        assert shared.region_reg is not None
        assert shared.region_reg.cache_dir == Path(tmp_path, "natural_earth")
        assert shared.region_reg.update is update

    def test_default_pipeline_caches_osmpp(self, tmp_path: Path) -> None:
        """Happy path: the default pipeline's OSMPP locator gets the `osmpp/` subfolder.

        Args:
            tmp_path (Path): Pytest-provided temporary directory (`resources_dir`).
        """
        build_shared_resources(source="eia", resources_dir=tmp_path)

        cast(MagicMock, pipelines.OSMPPLocator).assert_called_once_with(
            cache_dir=Path(tmp_path, "osmpp"), update=False
        )
