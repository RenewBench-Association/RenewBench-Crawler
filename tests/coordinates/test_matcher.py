# tests/coordinates/test_matcher.py
"""Tests for NameMatrixMatcher's generic SourceAdapter candidate builder."""

from types import SimpleNamespace
from typing import cast

import pandas as pd
import pytest

from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.matcher import (
    GEM_ADAPTER,
    OSM_ADAPTER,
    PPDB_ADAPTER,
    NameMatrixMatcher,
)


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def ppdb_df() -> pd.DataFrame:
    """Synthetic ppdb (here: PPM) candidate rows exercising the country/coordinate filters.

    Returns:
        pd.DataFrame: One Estonian row with an EIC (high confidence), one
            German row (filtered out by country), and one Estonian row with
            no coordinates (filtered out by the lat/lon requirement).
    """
    return pd.DataFrame(
        [
            {
                "Name": "Auvere Power Plant",
                "Country": "Estonia",
                "Fueltype": "Oil",
                "lat": 59.0,
                "lon": 27.0,
                "id": "ppdb-ppm-1",
                "EIC": "38W-KTJ-AUV-G1-8",
            },
            {
                "Name": "Some German Plant",
                "Country": "Germany",
                "Fueltype": "Oil",
                "lat": 50.0,
                "lon": 8.0,
                "id": "ppdb-ppm-2",
                "EIC": None,
            },
            {
                # No coordinates -> must be dropped
                "Name": "No Coords Plant",
                "Country": "Estonia",
                "Fueltype": "Oil",
                "lat": None,
                "lon": None,
                "id": "ppdb-ppm-3",
                "EIC": None,
            },
        ]
    )


@pytest.fixture
def gem_df() -> pd.DataFrame:
    """Synthetic GEM candidate row exercising the other_names column.

    Returns:
        pd.DataFrame: A single Estonian row with a comma-joined other_names
            value, to verify GEM_ADAPTER's other_names_col handling.
    """
    return pd.DataFrame(
        [
            {
                "plant_name": "Auvere",
                "other_names": "Auvere Elektrijaam, Auvere EJ",
                "Country": "Estonia",
                "Fueltype": "Oil",
                "lat": 59.01,
                "lon": 27.01,
                "gem_unit_id": "gem-1",
            }
        ]
    )


@pytest.fixture
def osm_df() -> pd.DataFrame:
    """Synthetic OSM candidate row with no Country column.

    Returns:
        pd.DataFrame: A single row, to verify OSM_ADAPTER's country_col=None
            handling (relies on the matrix-level country filter instead).
    """
    return pd.DataFrame(
        [
            {
                "Name": "Auvere jaam",
                "Fueltype": "Oil",
                "lat": 59.02,
                "lon": 27.02,
                "OSM_ID": "osm-1",
            }
        ]
    )


@pytest.fixture
def matcher(
    ppdb_df: pd.DataFrame,
    gem_df: pd.DataFrame,
    osm_df: pd.DataFrame,
) -> NameMatrixMatcher:
    """Returns a NameMatrixMatcher wired to fake ppdb (PPM)/GEM locators and an OSM df.

    Args:
        ppdb_df (pd.DataFrame): Synthetic ppdb (PPM) candidate rows.
        gem_df (pd.DataFrame): Synthetic GEM candidate rows.
        osm_df (pd.DataFrame): Synthetic OSM candidate rows.

    Returns:
        NameMatrixMatcher: Instance scoped to Estonia ("EE"), backed by fake
            locator objects (types.SimpleNamespace) so no real ppdb (PPM)/GEM
            downloads are needed.
    """
    return NameMatrixMatcher(
        country="Estonia",
        country_code="EE",
        gem_locator=cast(GEMLocator, SimpleNamespace(df_gem=gem_df)),
        ppdb_locator=cast(PPMLocator, SimpleNamespace(df=ppdb_df)),
        osm_df=osm_df,
    )


# ----------------------------------
# Tests
# ----------------------------------
def test_ppdb_adapter_country_filter_and_confidence(matcher: NameMatrixMatcher):
    """Happy path for PPDB_ADAPTER's country filter, coordinate filter, and confidence rule.

    Args:
        matcher (NameMatrixMatcher): Matcher scoped to Estonia, from the
            `matcher` fixture.
    """
    candidates = matcher._build_candidates(PPDB_ADAPTER)

    assert len(candidates) == 1  # only matching country = Estonia
    c = candidates[0]
    assert c.name == "Auvere Power Plant"
    assert c.source == "ppdb"
    assert c.source_id == "ppdb-ppm-1"
    assert c.country == "Estonia"
    assert c.confidence == "high"  # has EIC


def test_ppdb_adapter_medium_confidence_without_eic(ppdb_df: pd.DataFrame):
    """Failure path for PPDB_ADAPTER's confidence rule when the EIC column is empty.

    Args:
        ppdb_df (pd.DataFrame): Synthetic ppdb (PPM) candidate rows.
    """
    m = NameMatrixMatcher(
        country="Germany",
        country_code="DE",
        ppdb_locator=cast(PPMLocator, SimpleNamespace(df=ppdb_df)),
    )
    candidates = m._build_candidates(PPDB_ADAPTER)
    assert len(candidates) == 1
    assert candidates[0].confidence == "medium"  # no EIC


def test_gem_adapter_other_names_and_confidence(matcher: NameMatrixMatcher):
    """Happy path for GEM_ADAPTER's other_names_col and constant "high" confidence.

    Args:
        matcher (NameMatrixMatcher): Matcher scoped to Estonia, from the
            `matcher` fixture.
    """
    candidates = matcher._build_candidates(GEM_ADAPTER)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.source == "gem"
    assert c.source_id == "gem-1"
    assert c.confidence == "high"
    assert c.other_names == "Auvere Elektrijaam, Auvere EJ"


def test_osm_adapter_no_country_column(matcher: NameMatrixMatcher):
    """Happy path for OSM_ADAPTER when the source has no country column.

    Args:
        matcher (NameMatrixMatcher): Matcher scoped to Estonia, from the
            `matcher` fixture.
    """
    candidates = matcher._build_candidates(OSM_ADAPTER)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.source == "osm"
    assert c.source_id == "osm-1"
    assert c.country is None
    assert c.confidence == "medium"


def test_build_candidates_missing_locator_returns_empty():
    """Failure path: a matcher with no locator wired up returns no candidates."""
    m = NameMatrixMatcher(country="Estonia")
    assert m._build_candidates(PPDB_ADAPTER) == []
    assert m._build_candidates(GEM_ADAPTER) == []


def test_build_matrix_uses_all_three_adapters(matcher: NameMatrixMatcher):
    """Happy path for build_matrix: candidates from all three sources are present.

    Args:
        matcher (NameMatrixMatcher): Matcher scoped to Estonia, from the
            `matcher` fixture.
    """
    matrix = matcher.build_matrix()
    all_candidates = [c for candidates in matrix.values() for c in candidates]
    sources = {c.source for c in all_candidates}
    assert sources == {"ppdb", "gem", "osm"}
