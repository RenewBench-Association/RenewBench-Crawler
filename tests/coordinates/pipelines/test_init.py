# tests/coordinates/pipelines/test_init.py
"""Tests for the pipelines package's __init__ helpers."""

from pathlib import Path
from typing import Any

import pytest

from rbc.coordinates.locators.eic_registry import EICCodeRegistry
from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.pipelines import build_shared_locators, make_pipeline
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


class TestBuildSharedLocators:
    """Test the 'build_shared_locators' function."""

    def test_default_pipeline(self) -> None:
        """Happy path: default pipeline builds a OSMPP ppdb, a GEM loc but no EIC registry."""
        shared = build_shared_locators(source="eia", gem_dir=None, output_dir=None)
        assert isinstance(shared.ppdb_loc, OSMPPLocator)
        assert isinstance(shared.gem_loc, GEMLocator)
        assert shared.eic_reg is None

    def test_entsoe_pipeline(self) -> None:
        """Happy path: entsoe pipeline builds a PPM ppdb, a GEM loc and an EIC registry."""
        shared = build_shared_locators(source="entsoe", gem_dir=None, output_dir=None)
        assert isinstance(shared.ppdb_loc, PPMLocator)
        assert isinstance(shared.gem_loc, GEMLocator)
        assert shared.eic_reg is not None
        assert isinstance(shared.eic_reg, EICCodeRegistry)
