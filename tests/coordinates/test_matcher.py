# tests/coordinates/test_matcher.py
"""Tests for the matcher's NameMatcher and the locators' column-mapping schemas."""

import pandas as pd
import pytest
from loguru import logger

from rbc.coordinates.map import MATCH_METHOD_COLORS
from rbc.coordinates.match_schema import (
    GEM_SCHEMA,
    LOCATOR_RELIABILITY,
    LOCATOR_SCHEMAS,
    OSM_SCHEMA,
    PPDB_SCHEMA,
    MatchCandidate,
)
from rbc.coordinates.matcher import NameMatcher
from rbc.coordinates.utils.tokenizer import NameTokenizer


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def gem_df() -> pd.DataFrame:
    """Synthetic GEM candidate row exercising the other_names column.

    Returns:
        pd.DataFrame: A single Estonian row with a comma-joined other_names
            value, to verify GEM_SCHEMA's other_names_col handling.
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
        pd.DataFrame: A single row, to verify OSM_SCHEMA's country_col=None
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
    """Returns a NameMatcher wired to synthetic candidate rows of all three locators.

    Args:
        ppdb_df (pd.DataFrame): Synthetic ppdb (PPM) candidate rows.
        gem_df (pd.DataFrame): Synthetic GEM candidate rows.
        osm_df (pd.DataFrame): Synthetic OSM candidate rows.

    Returns:
        NameMatcher: Instance scoped to Estonia ("EE"), backed by dataframes only, so no
            real ppdb (PPM)/GEM downloads are needed.
    """
    return NameMatcher(
        country="Estonia",
        tok=NameTokenizer(),
        gem_df=gem_df,
        ppdb_df=ppdb_df,
        osm_df=osm_df,
    )


# ----------------------------------
# Tests
# ----------------------------------
class TestLocatorSchemas:
    """Tests for building candidates through each locator's column mapping."""

    def test_gem_schema(self, matcher: NameMatcher) -> None:
        """Happy path for GEM_SCHEMA, where other_names are made their own candidates.

        Args:
            matcher (NameMatcher): Matcher scoped to Estonia from the `matcher` fixture.
        """
        candidates = matcher._build_candidates(GEM_SCHEMA)
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

    def test_ppdb_schema(self, matcher: NameMatcher) -> None:
        """Happy path for PPDB_SCHEMA with country and coordinate filters.

        Args:
            matcher (NameMatcher): Matcher scoped to Estonia, from the `matcher` fixture.
        """
        candidates = matcher._build_candidates(PPDB_SCHEMA)

        assert len(candidates) == 1  # only matching country = Estonia
        c = candidates[0]
        assert c.name == "Auvere Power Plant"
        assert c.locator == "ppdb"
        assert c.id == "ppdb-ppm-1"
        assert c.country == "Estonia"

    def test_ppdb_schema_filter_target_country(self, ppdb_df: pd.DataFrame) -> None:
        """Happy path: PPDB_SCHEMA keeps the row matching the matcher's own country.

        The same fixture yields the Estonian row for an Estonian matcher (above) and the
        German one here, so the filter is shown to follow the target rather than the data.

        Args:
            ppdb_df (pd.DataFrame): Synthetic ppdb (PPM) candidate rows.
        """
        m = NameMatcher(
            country="Germany",
            tok=NameTokenizer(),
            ppdb_df=ppdb_df,
        )
        candidates = m._build_candidates(PPDB_SCHEMA)

        assert len(candidates) == 1
        assert candidates[0].id == "ppdb-ppm-2"
        assert candidates[0].country == "Germany"

    def test_osm_schema(self, matcher: NameMatcher) -> None:
        """Happy path for OSM_SCHEMA with no country column.

        Args:
            matcher (NameMatcher): Matcher scoped to Estonia from the `matcher` fixture.
        """
        candidates = matcher._build_candidates(OSM_SCHEMA)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.locator == "osm"
        assert c.id == "osm-1"
        assert c.country is None


class TestCandidateFrames:
    """Tests that every locator's schema can be fed a dataframe by the matcher."""

    def test_every_schema_has_a_frame_slot(self) -> None:
        """Happy path: the matcher holds one candidate-frame slot per locator schema.

        `_build_candidates` looks its frame up by `schema.locator`, so a schema with no
        slot contributes no candidates at all -- silently, since a missing key is None.
        """
        matcher = NameMatcher(country="Estonia", tok=NameTokenizer())

        assert set(matcher.candidate_dfs) == {s.locator for s in LOCATOR_SCHEMAS}


class TestLocatorReliability:
    """Tests for the reliability order that breaks ties between equal scores."""

    def test_locators_rank_gem_over_ppdb_over_osm(self) -> None:
        """Happy path: GEM outranks the power plant databases, which outrank raw OSM.

        The order decides which candidate wins when two locators score the same (s.
        NameMatcher.match), and it is what LOCATOR_SCHEMAS is sorted by.
        """
        assert (
            LOCATOR_RELIABILITY["gem"]
            > LOCATOR_RELIABILITY["ppdb"]
            > LOCATOR_RELIABILITY["osm"]
        )
        assert [s.locator for s in LOCATOR_SCHEMAS] == ["gem", "ppdb", "osm"]


class TestMatchCandidateConstruction:
    """Tests for MatchCandidate's factory methods (`from_row`, `primary_from_row`).

    Happy path for `from_row` is already indirectly covered by TestLocatorSchemas.
    """

    @pytest.mark.parametrize(
        "schema, frame, expected",
        [("gem", "gem_df", "gem"), ("ppdb", "ppdb_df", "ppdb")],
    )
    def test_to_dict_prefixes_columns_with_its_own_locator(
        self,
        request: pytest.FixtureRequest,
        schema: str,
        frame: str,
        expected: str,
    ) -> None:
        """Happy path: a candidate publishes its columns under its own locator's name.

        The locator field never becomes a column of its own: it names the others,
        which is what keeps the pipelines' `<loc>.*` columns apart.

        Args:
            request (pytest.FixtureRequest): Pytest-provided request to get the fixture.
            schema (str): Which locator's schema builds the candidate ("gem"/"ppdb").
            frame (str): Name of the locator's dataframe fixture.
            expected (str): The locator name every column must be prefixed with.
        """
        schemas = {"gem": GEM_SCHEMA, "ppdb": PPDB_SCHEMA}
        row = request.getfixturevalue(frame).iloc[0]
        candidate = MatchCandidate.from_row(row, schemas[schema])[0]

        cols = candidate.to_dict()
        assert cols
        assert all(col.startswith(f"{expected}.") for col in cols)
        assert f"{expected}.locator" not in cols  # internal, never published

    def test_from_row_no_name_returns_empty(self, gem_df: pd.DataFrame) -> None:
        """Failure path: from_row returns [] when the row has no primary name.

        Args:
            gem_df (pd.DataFrame): Synthetic GEM rows (here using first row = Estonia).
        """
        row = gem_df.iloc[0].copy()
        row["plant_name"] = None
        assert MatchCandidate.from_row(row, schema=GEM_SCHEMA) == []

    def test_from_row_missing_id_skipped(self, gem_df: pd.DataFrame) -> None:
        """Failure path: from_row skips and warns for a row whose locator id is missing.

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
            assert MatchCandidate.from_row(row, schema=GEM_SCHEMA) == []
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
        candidate = MatchCandidate.primary_from_row(gem_df.iloc[0], schema=GEM_SCHEMA)
        assert candidate is not None
        assert candidate.name == "Auvere"
        assert candidate.primary_name == "Auvere"
        assert candidate.id == "gem-1"

    def test_primary_from_row_no_name_returns_none(self, gem_df: pd.DataFrame) -> None:
        """Failure path: primary_from_row returns None when the row has no name.

        Args:
            gem_df (pd.DataFrame): Synthetic GEM rows (here using first row = Estonia).
        """
        row = gem_df.iloc[0].copy()
        row["plant_name"] = None
        assert MatchCandidate.primary_from_row(row, schema=GEM_SCHEMA) is None


class TestNameMatcherCachedProperties:
    """Tests for NameMatcher cached properties."""

    def test_candidate_index(self, matcher: NameMatcher) -> None:
        """Happy path: candidates from every locator, and the property builds only once.

        Args:
            matcher (NameMatcher): Matcher scoped to Estonia from the `matcher` fixture.
        """
        index = matcher._candidate_index
        all_candidates = [c for candidates in index.values() for c in candidates]
        locators = {c.locator for c in all_candidates}

        assert locators == {"ppdb", "gem", "osm"}
        assert index is matcher._candidate_index
        assert "_candidate_index" in matcher.__dict__  # cached on the instance

    def test_candidate_index_empty_is_still_cached(self) -> None:
        """Failure path: If locators yield nothing, an empty index is cached."""
        m = NameMatcher(country="Estonia", tok=NameTokenizer())
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
            tok=NameTokenizer(),
            gem_df=gem_df,
        )
        result = matcher.match("Mauá Bloco 6", target_fueltype="hydro")

        assert result.matched
        assert result.candidate is not None
        assert result.candidate.id == "gem-maua-6"

        # the wrong unit is still a candidate, just a strictly worse-scoring one
        scores = {cand.id: score for cand, score in result.top_matches}
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
            tok=NameTokenizer(),
            gem_df=gem_df,
        )
        result = matcher.match("Mauá Bloco 6", target_fueltype="hydro")
        assert len(result.top_matches) == 2


class TestNameMatcherMatchedVia:
    """Tests for `matched_via`, which names the approach the winning match came from."""

    @pytest.mark.parametrize(
        "target, expected",
        [
            ("Auvere", "name_exact"),  # hits the primary name's index key
            ("Auvere Elektrijaam", "name_exact"),  # hits an other_names variant's key
            ("Auvere EJ 1", "name_fuzzy"),  # no key hit, wins on weighted tokens
        ],
    )
    def test_approach_is_published(
        self, gem_df: pd.DataFrame, target: str, expected: str
    ) -> None:
        """Happy path: a match reports whether it came from a key hit or token scoring.

        Args:
            gem_df (pd.DataFrame): Synthetic GEM rows (here using the Estonian row).
            target (str): Parametrized target name to match.
            expected (str): The approach expected to win.
        """
        matcher = NameMatcher(
            country="Estonia",
            tok=NameTokenizer(),
            gem_df=gem_df,
        )
        result = matcher.match(target, target_fueltype="oil")

        assert result.matched
        assert result.matched_via == expected
        # the published value has to compose into a known match_method (s. test_map.py)
        assert f"gem_{result.matched_via}" in MATCH_METHOD_COLORS

    def test_score_cannot_stand_in_for_the_approach(self, gem_df: pd.DataFrame) -> None:
        """Happy path: both approaches can score alike, hence the separate field.

        Args:
            gem_df (pd.DataFrame): Synthetic GEM rows (here using the Estonian row).
        """
        matcher = NameMatcher(
            country="Estonia",
            tok=NameTokenizer(),
            gem_df=gem_df,
        )
        exact = matcher.match("Auvere", target_fueltype="oil")
        fuzzy = matcher.match("Auvere EJ 1", target_fueltype="oil")

        assert exact.score == fuzzy.score
        assert exact.matched_via != fuzzy.matched_via

    def test_unmatched_has_no_approach(self, gem_df: pd.DataFrame) -> None:
        """Failure path: a target that wins nothing reports no approach at all.

        Args:
            gem_df (pd.DataFrame): Synthetic GEM rows (here using the Estonian row).
        """
        matcher = NameMatcher(
            country="Estonia",
            tok=NameTokenizer(),
            gem_df=gem_df,
        )
        result = matcher.match("Auvere jaam plant", target_fueltype="oil")

        assert not result.matched
        assert result.matched_via is None


class TestNameMatcherHelpers:
    """Tests for NameMatcher helpers."""

    def test_build_candidates_missing_locator_returns_empty(self) -> None:
        """Failure path: A matcher with no locator wired up returns no candidates."""
        m = NameMatcher(country="Estonia", tok=NameTokenizer())
        assert m._build_candidates(PPDB_SCHEMA) == []
        assert m._build_candidates(GEM_SCHEMA) == []
