# tests/coordinates/pipelines/conftest.py
"""Shared fixtures for coordinate-finding pipeline tests."""

from unittest.mock import create_autospec

import pandas as pd
import pytest

from rbc.coordinates.locators.eic_registry import EICCodeRegistry
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.locators.ppm import PPMLocator


@pytest.fixture(autouse=True)  # applied to all test files in the pipeline directory
def mock_expensive_network_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every network-hitting locator/query with mock stand-ins.

    Constructing a pipeline can trigger real network I/O in two ways:
    1. locator classes (PPM, OSMPP, EICCodeRegistry) fetch remote CSVs when instantiated
        -> use `create_autospec` to return something that passes assert statements.
    2. `query_osm_country_plants` requests an OSM df from the Overpass API
        -> patch to return an empty DataFrame (can be overwritten when true df is needed).

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest-provided monkeypatch fixture.
    """
    for module in ("rbc.coordinates.pipelines", "rbc.coordinates.pipelines.default"):
        monkeypatch.setattr(f"{module}.OSMPPLocator", create_autospec(OSMPPLocator))
    for module in ("rbc.coordinates.pipelines", "rbc.coordinates.pipelines.entsoe"):
        monkeypatch.setattr(f"{module}.PPMLocator", create_autospec(PPMLocator))
        monkeypatch.setattr(
            f"{module}.EICCodeRegistry", create_autospec(EICCodeRegistry)
        )

    monkeypatch.setattr(
        "rbc.coordinates.pipelines._base.query_osm_country_plants",
        lambda *args, **kwargs: pd.DataFrame(),
    )
