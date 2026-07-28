# tests/coordinates/pipelines/test_init.py
"""Tests for the pipelines package's __init__ helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rbc.coordinates.pipelines import build_shared_locators, make_pipeline
from rbc.coordinates.pipelines.default import DefaultPipeline
from rbc.coordinates.pipelines.entsoe import EntsoePipeline


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture(autouse=True)
def mock_expensive_locators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace PPMLocator/EICDirectoryLocator with mocks everywhere they're constructed.

    `PPMLocator()` and `EICDirectoryLocator()` do real network I/O (a PPM CSV
    download and an ENTSO-E EIC registry fetch respectively) as soon as they're
    instantiated. `make_pipeline`/`build_shared_locators` build one or both of
    these whenever a caller doesn't pass an existing instance in -- which is
    every test in this file -- so leaving them real makes these unit tests slow
    and network-dependent. Patch the class at each of its three import sites.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest-provided monkeypatch fixture.
    """
    monkeypatch.setattr("rbc.coordinates.pipelines.PPMLocator", MagicMock())
    monkeypatch.setattr("rbc.coordinates.pipelines.EICDirectoryLocator", MagicMock())
    monkeypatch.setattr("rbc.coordinates.pipelines.default.PPMLocator", MagicMock())
    monkeypatch.setattr("rbc.coordinates.pipelines.entsoe.PPMLocator", MagicMock())
    monkeypatch.setattr(
        "rbc.coordinates.pipelines.entsoe.EICDirectoryLocator", MagicMock()
    )


@pytest.fixture
def eia_zone_dir(tmp_path: Path) -> Path:
    """A real "eia" operator directory (default pipeline).

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        Path: The "eia/US48" zone directory.
    """
    zone_dir = tmp_path / "eia" / "US48"
    zone_dir.mkdir(parents=True)
    return zone_dir


@pytest.fixture
def entsoe_zone_dir(tmp_path: Path) -> Path:
    """A real "entsoe" operator directory (entsoe pipeline).

    Args:
        tmp_path (Path): Pytest-provided temporary directory.

    Returns:
        Path: The "entsoe/10YNL----------L" zone directory.
    """
    zone_dir = tmp_path / "entsoe" / "10YNL----------L"
    zone_dir.mkdir(parents=True)
    return zone_dir


# ----------------------------------
# Tests: make_pipeline
# ----------------------------------
def test_make_pipeline_resolves_default_for_non_entsoe_operator(eia_zone_dir: Path):
    """Happy path: any operator other than entsoe resolves to DefaultPipeline.

    Args:
        eia_zone_dir (Path): Synthetic "eia/US48" zone directory.
    """
    pipeline = make_pipeline(input_dir=eia_zone_dir)
    assert isinstance(pipeline, DefaultPipeline)


def test_make_pipeline_resolves_entsoe_pipeline(entsoe_zone_dir: Path):
    """Happy path: the entsoe operator resolves to EntsoePipeline.

    Args:
        entsoe_zone_dir (Path): Synthetic "entsoe/10YNL----------L" zone directory.
    """
    pipeline = make_pipeline(input_dir=entsoe_zone_dir)
    assert isinstance(pipeline, EntsoePipeline)


def test_make_pipeline_never_forwards_eicloc_to_default_pipeline(eia_zone_dir: Path):
    """DefaultPipeline's constructor doesn't accept eicloc at all.

    Passing one for a non-entsoe directory must not raise (it's silently not forwarded).

    Args:
        eia_zone_dir (Path): Synthetic "eia/US48" zone directory.
    """
    pipeline = make_pipeline(input_dir=eia_zone_dir, eicloc=object())  # type: ignore[arg-type]
    assert isinstance(pipeline, DefaultPipeline)


# ----------------------------------
# Tests: build_shared_locators
# ----------------------------------
def test_build_shared_locators_skips_ppm_and_eic_for_default_pipeline():
    """Happy path: a non-entsoe source gets no ppmloc/eicloc (PPM/EIC are entsoe-only)."""
    shared = build_shared_locators(source="eia", gem_dir=None, output_dir=None)
    assert shared.ppmloc is None
    assert shared.eicloc is None


def test_build_shared_locators_builds_ppm_and_eic_for_entsoe():
    """Happy path: entsoe gets real ppmloc/eicloc instances built up front."""
    shared = build_shared_locators(source="entsoe", gem_dir=None, output_dir=None)
    assert shared.ppmloc is not None
    assert shared.eicloc is not None


def test_build_shared_locators_skips_gem_without_gem_dir():
    """Failure path: gemloc stays disabled (None) when no gem_dir is provided."""
    shared = build_shared_locators(source="eia", gem_dir=None, output_dir=None)
    assert shared.gemloc is None
