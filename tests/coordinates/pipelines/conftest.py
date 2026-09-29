# tests/coordinates/pipelines/conftest.py
"""Shared fixtures for coordinate-finding pipeline tests."""

from unittest.mock import create_autospec

import pandas as pd
import pytest

from rbc.coordinates.locators.eic_registry import EICCodeRegistry
from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.osmpp import OSMPPLocator
from rbc.coordinates.locators.ppm import PPMLocator


@pytest.fixture(autouse=True)  # applied to all test files in the pipeline directory
def mock_expensive_network_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every network-hitting locator/query with mock stand-ins.

    A run can trigger real network I/O in two ways:
    1. `build_shared_resources` constructs the locator classes, which fetch remote CSVs
        -> use `create_autospec` to return something that passes assert statements.
        The pipelines themselves construct nothing: a locator they are not given is
        simply absent (contributes no candidates).
    2. `OverpassLocator.get_country_df` requests an OSM df from the Overpass API
        -> patch to return an empty DataFrame (can be overwritten when true df is needed).

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest-provided monkeypatch fixture.
    """
    module = "rbc.coordinates.pipelines"  # where build_shared_resources builds them
    monkeypatch.setattr(f"{module}.GEMLocator", create_autospec(GEMLocator))
    monkeypatch.setattr(f"{module}.OSMPPLocator", create_autospec(OSMPPLocator))
    monkeypatch.setattr(f"{module}.PPMLocator", create_autospec(PPMLocator))
    monkeypatch.setattr(f"{module}.EICCodeRegistry", create_autospec(EICCodeRegistry))

    monkeypatch.setattr(
        "rbc.coordinates.locators.osm_api.OverpassLocator.get_country_df",
        lambda *args, **kwargs: pd.DataFrame(),
    )
