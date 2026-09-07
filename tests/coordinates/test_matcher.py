# tests/coordinates/test_matcher.py
"""Tests for the matcher's NameMatcher and coordinate finding source Adapter classes."""

from types import SimpleNamespace
from typing import cast

import pandas as pd
import pytest
from loguru import logger

from rbc.coordinates.locators.gem import GEMLocator
from rbc.coordinates.locators.ppm import PPMLocator
from rbc.coordinates.match_schema import (
    GEM_ADAPTER,
    OSM_ADAPTER,
    PPDB_ADAPTER,
    MatchCandidate,
)
from rbc.coordinates.matcher import NameMatcher


# ----------------------------------
# Fixtures
# ----------------------------------
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
            },
            {
                "plant_name": "Mauá 3 power plant",
                "other_names": "",
                "Country": "Brazil",
                "Fueltype": "hydro",
                "lat": -1.9,
                "lon": -59.4,
                "gem_unit_id": "gem-maua-3",
            },
            {
                "plant_name": "Mauá 6 power plant",
                "other_names": "",
                "Country": "Brazil",
                "Fueltype": "hydro",
                "lat": -2.9,
                "lon": -59.4,
                "gem_unit_id": "gem-maua-6",
            },
        ]
    )


@pytest.fixture
def ppdb_df() -> pd.DataFrame:
    """Synthetic ppdb (here: PPM) candidate rows exercising the country/coordinate filters.

    Returns:
        pd.DataFrame: One Estonian row, one German row (filtered out by country
            for an Estonian matcher) and one Estonian row with no coordinates
            (filtered out by the lat/lon requirement).
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
) -> NameMatcher:
    """Returns a NameMatcher wired to fake ppdb (PPM)/GEM locators and an OSM df.

    Args:
        ppdb_df (pd.DataFrame): Synthetic ppdb (PPM) candidate rows.
        gem_df (pd.DataFrame): Synthetic GEM candidate rows.
        osm_df (pd.DataFrame): Synthetic OSM candidate rows.

    Returns:
        NameMatcher: Instance scoped to Estonia ("EE"), backed by fake
            locator objects (types.SimpleNamespace) so no real ppdb (PPM)/GEM
            downloads are needed.
    """
    return NameMatcher(
        country="Estonia",
        gem_locator=cast(GEMLocator, SimpleNamespace(df=gem_df)),
        ppdb_locator=cast(PPMLocator, SimpleNamespace(df=ppdb_df)),
        osm_df=osm_df,
    )


# ----------------------------------
# Tests
# ----------------------------------
class TestAdapters:
    """Tests for the coordinate / location finding source Adapter classes."""

    def test_gem_adapter(self, matcher: NameMatcher) -> None:
        """Happy path for GEM_ADAPTER, where other_names are made their own candidates.

        Args:
            matcher (NameMatcher): Matcher scoped to Estonia from the `matcher` fixture.
        """
        candidates = matcher._build_candidates(GEM_ADAPTER)
        assert len(candidates) == 3
        assert all(c.ege_key == ("gem", "gem-1") for c in candidates)
        assert all(c.primary_name == "Auvere" for c in candidates)
        assert [c.name for c in candidates] == [
            "Auvere",
            "Auvere Elektrijaam",
            "Auvere EJ",
        ]
        assert [c.norm_name for c in candidates] == [
            "auvere",
            "auvere elektrijaam",
            "auvere ej",
        ]

    def test_ppdb_adapter(self, matcher: NameMatcher) -> None:
        """Happy path for PPDB_ADAPTER with country and coordinate filters.

        Args:
            matcher (NameMatcher): Matcher scoped to Estonia, from the `matcher` fixture.
        """
        candidates = matcher._build_candidates(PPDB_ADAPTER)

        assert len(candidates) == 1  # only matching country = Estonia
        c = candidates[0]
        assert c.name == "Auvere Power Plant"
        assert c.source == "ppdb"
        assert c.source_id == "ppdb-ppm-1"
        assert c.country == "Estonia"

    def test_ppdb_adapter_filter_target_country(self, ppdb_df: pd.DataFrame) -> None:
        """Happy path: PPDB_ADAPTER keeps the row matching the matcher's own country.

        The same fixture yields the Estonian row for an Estonian matcher (above) and the
        German one here, so the filter is shown to follow the target rather than the data.

        Args:
            ppdb_df (pd.DataFrame): Synthetic ppdb (PPM) candidate rows.
        """
        m = NameMatcher(
            country="Germany",
            ppdb_locator=cast(PPMLocator, SimpleNamespace(df=ppdb_df)),
        )
        candidates = m._build_candidates(PPDB_ADAPTER)

        assert len(candidates) == 1
        assert candidates[0].source_id == "ppdb-ppm-2"
        assert candidates[0].country == "Germany"

    def test_osm_adapter(self, matcher: NameMatcher) -> None:
        """Happy path for OSM_ADAPTER with no country column.

        Args:
            matcher (NameMatcher): Matcher scoped to Estonia from the `matcher` fixture.
        """
        candidates = matcher._build_candidates(OSM_ADAPTER)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.source == "osm"
        assert c.source_id == "osm-1"
        assert c.country is None


class TestMatchCandidateConstruction:
    """Tests for MatchCandidate's factory methods (`from_row`, `primary_from_row`).

    Happy path for `from_row` is already indirectly covered by TestAdapters.
    """

    def test_from_row_no_name_returns_empty(self, gem_df: pd.DataFrame) -> None:
        """Failure path: from_row returns [] when the row has no primary name.

        Args:
            gem_df (pd.DataFrame): Synthetic GEM rows (here using first row = Estonia).
        """
        row = gem_df.iloc[0].copy()
        row["plant_name"] = None
        assert MatchCandidate.from_row(row, loc=GEM_ADAPTER) == []

    def test_from_row_missing_source_id_skipped(self, gem_df: pd.DataFrame) -> None:
        """Failure path: from_row skips and warns for a row whose source_id is missing.

        Args:
            gem_df (pd.DataFrame): Synthetic GEM rows (here using first row = Estonia).
        """
        captured_logs: list[dict] = []
        sink_id = logger.add(
            lambda msg: captured_logs.append(msg.record), level="WARNING"
        )
        try:
            row = gem_df.iloc[0].copy()
            row["gem_unit_id"] = None
            assert MatchCandidate.from_row(row, loc=GEM_ADAPTER) == []
            assert len(captured_logs) == 1
            assert "missing gem_unit_id" in captured_logs[0]["message"]
            assert "Auvere" in captured_logs[0]["message"]
        finally:
            logger.remove(sink_id)

    def test_primary_from_row(self, gem_df: pd.DataFrame) -> None:
        """Happy path: primary_from_row returns only the primary variant.

        Args:
            gem_df (pd.DataFrame): Synthetic GEM rows (here using first row = Estonia).
        """
        candidate = MatchCandidate.primary_from_row(gem_df.iloc[0], loc=GEM_ADAPTER)
        assert candidate is not None
        assert candidate.name == "Auvere"
        assert candidate.primary_name == "Auvere"
        assert candidate.source_id == "gem-1"

    def test_primary_from_row_no_name_returns_none(self, gem_df: pd.DataFrame) -> None:
        """Failure path: primary_from_row returns None when the row has no name.

        Args:
            gem_df (pd.DataFrame): Synthetic GEM rows (here using first row = Estonia).
        """
        row = gem_df.iloc[0].copy()
        row["plant_name"] = None
        assert MatchCandidate.primary_from_row(row, loc=GEM_ADAPTER) is None


class TestNameMatcherCachedProperties:
    """Tests for NameMatcher cached properties."""

    def test_candidate_index(self, matcher: NameMatcher) -> None:
        """Happy path: candidates based on all sources and cached property builds only once.

        Args:
            matcher (NameMatcher): Matcher scoped to Estonia from the `matcher` fixture.
        """
        index = matcher._candidate_index
        all_candidates = [c for candidates in index.values() for c in candidates]
        sources = {c.source for c in all_candidates}

        assert sources == {"ppdb", "gem", "osm"}
        assert index is matcher._candidate_index
        assert "_candidate_index" in matcher.__dict__  # cached on the instance

    def test_candidate_index_empty_is_still_cached(self) -> None:
        """Failure path: If sources yield nothing, an empty index is cached (no rebuild)."""
        m = NameMatcher(country="Estonia")
        assert m._candidate_index == {}
        assert "_candidate_index" in m.__dict__


class TestNameMatcherTargetVariants:
    """Tests for ordered target_variants (built: _generate_target_variants, used: match)."""

    def test_match_stop_at_fitting_target(self, gem_df: pd.DataFrame) -> None:
        """Happy path: The unit number decides between two units of the same plant.

        _generate_target_variants also returns a unit-stripped variant ("maua"), which scores
        100 against every Mauá unit. The variant check in match must stop at the
        first variant that wins -- here the full name.

        Args:
            gem_df (pd.DataFrame): Synthetic GEM rows (here using 2nd & 3rd rows = Brazil).
        """
        matcher = NameMatcher(
            country="Brazil",
            gem_locator=cast(GEMLocator, SimpleNamespace(df=gem_df)),
        )
        result = matcher.match("Mauá Bloco 6", target_fueltype="hydro")

        assert result.matched
        assert result.candidate is not None
        assert result.candidate.source_id == "gem-maua-6"

        # the wrong unit is still a candidate, just a strictly worse-scoring one
        scores = {cand.source_id: score for cand, score in result.top_matches}
        assert scores["gem-maua-6"] > scores["gem-maua-3"]

    def test_match_check_all_candidates(self, gem_df: pd.DataFrame) -> None:
        """Happy path: Target variant matching never stops mid-candidate-loop.

        Loop is broken ONLY when the full _candidate_index has been checked to find the
        best match for a target variant.

        Args:
            gem_df (pd.DataFrame): Synthetic GEM rows (here using 2nd & 3rd rows = Brazil).
        """
        matcher = NameMatcher(
            country="Brazil",
            gem_locator=cast(GEMLocator, SimpleNamespace(df=gem_df)),
        )
        result = matcher.match("Mauá Bloco 6", target_fueltype="hydro")
        assert len(result.top_matches) == 2


class TestNameMatcherHelpers:
    """Tests for NameMatcher helpers."""

    def test_build_candidates_missing_locator_returns_empty(self) -> None:
        """Failure path: A matcher with no locator wired up returns no candidates."""
        m = NameMatcher(country="Estonia")
        assert m._build_candidates(PPDB_ADAPTER) == []
        assert m._build_candidates(GEM_ADAPTER) == []
