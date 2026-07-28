# tests/coordinates/pipelines/test_init.py
"""Tests for the pipelines package's __init__ helpers."""

from pathlib import Path
from typing import Any
from unittest.mock import create_autospec

import pytest

from rbc.coordinates.locators.eic_registry import EICCodeRegistry
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.pipelines import build_shared_locators, make_pipeline
from rbc.coordinates.pipelines.default import DefaultPipeline
from rbc.coordinates.pipelines.entsoe import EntsoePipeline


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture(autouse=True)
def mock_expensive_locators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ppdb locators / EICCodeRegistry with autospecced mocks wherever constructed.

    Locators (PPM, OSMPP, EICCodeRegistry) do real network I/O when they're instantiated.
    As the here tested functions use them, leaving them real makes these unit tests slow
    and network-dependent.

    `create_autospec` (rather than a bare `MagicMock()`) is required here: the code under
    test calls these as constructors (e.g. `OSMPPLocator()`), and callers like
    `test_default_pipeline`/`test_entsoe_pipeline` below assert `isinstance(result, ...)`
    on what that call returns -- a bare `MagicMock()` returns a generic `MagicMock` on
    call, which fails `isinstance`; `create_autospec` makes the call return an
    autospecced instance that passes it.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest-provided monkeypatch fixture.
    """
    monkeypatch.setattr(
        "rbc.coordinates.pipelines.OSMPPLocator", create_autospec(OSMPPLocator)
    )
    monkeypatch.setattr(
        "rbc.coordinates.pipelines.PPMLocator", create_autospec(PPMLocator)
    )
    monkeypatch.setattr(
        "rbc.coordinates.pipelines.EICCodeRegistry", create_autospec(EICCodeRegistry)
    )
    monkeypatch.setattr(
        "rbc.coordinates.pipelines.default.OSMPPLocator", create_autospec(OSMPPLocator)
    )
    monkeypatch.setattr(
        "rbc.coordinates.pipelines.entsoe.PPMLocator", create_autospec(PPMLocator)
    )
    monkeypatch.setattr(
        "rbc.coordinates.pipelines.entsoe.EICCodeRegistry",
        create_autospec(EICCodeRegistry),
    )


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
        """Happy path: default pipeline builds OSMPP ppdb, no EIC registry, no GEM if none."""
        shared = build_shared_locators(source="eia", gem_dir=None, output_dir=None)
        assert isinstance(shared.ppdb_loc, OSMPPLocator)
        assert shared.eic_reg is None
        assert shared.gem_loc is None

    def test_entsoe_pipeline(self) -> None:
        """Happy path: entsoe pipeline builds PPM ppdb, a EIC registry, no GEM if none."""
        shared = build_shared_locators(source="entsoe", gem_dir=None, output_dir=None)
        assert isinstance(shared.ppdb_loc, PPMLocator)
        assert shared.eic_reg is not None
        assert shared.gem_loc is None
