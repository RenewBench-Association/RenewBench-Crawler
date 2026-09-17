# tests/coordinates/locators/test_osm_api.py
"""Tests for the Overpass API client: endpoint fallback, caching and tag parsing."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from rbc.coordinates.locators.osm_api import (
    OVERPASS_URLS,
    OverpassLocator,
    _elements_to_df,
    _parse_coordinates,
    post_overpass,
)

# Overpass reports server-side failures as HTTP 200 with the error only in "remark"
TIMEOUT_REMARK = (
    'runtime error: Query timed out in "query" at line 3 after 301 seconds.'
)
MEMORY_REMARK = "runtime error: Query run out of memory using about 2048 MB of RAM."

# A minimal named EGE, as Overpass returns it
EGE = {
    "type": "node",
    "id": 1,
    "lat": -23.5,
    "lon": -46.6,
    "tags": {"power": "plant", "name": "Usina A"},
}


# ----------------------------------
# Fixtures
# ----------------------------------
def _overpass_response(body: dict) -> MagicMock:
    """Build a stand-in for a `requests.Response` with HTTP 200 and the given JSON body.

    Args:
        body (dict): Parsed JSON the response should return.

    Returns:
        MagicMock: Double with `status_code`, `json()` and `raise_for_status()`.
    """
    response = MagicMock(status_code=200)
    response.json.return_value = body
    return response


def _cached_parquet(cache_dir: Path, name: str) -> Path:
    """Write a one-plant OSM parquet cache for Brazil, as a previous run would have.

    Args:
        cache_dir (Path): Directory the cache is written to.
        name (str): Name of the single cached plant.

    Returns:
        Path: Path of the written parquet file.
    """
    parquet_path = Path(cache_dir, "overpass_BR.parquet")
    pd.DataFrame({"Name": [name]}).to_parquet(parquet_path, index=False)
    return parquet_path


# ----------------------------------
# Tests - post_overpass
# ----------------------------------
class TestPostOverpass:
    """Tests for post_overpass."""

    @pytest.mark.parametrize(
        "failed_body",
        [
            pytest.param({"elements": [], "remark": TIMEOUT_REMARK}),
            pytest.param({"elements": [], "remark": MEMORY_REMARK}),
            pytest.param({"elements": [EGE], "remark": TIMEOUT_REMARK}),
            pytest.param({"elements": []}),
        ],
        ids=[
            "timeout-remark",
            "memory-remark",
            "remark-with-elements",
            "empty-wo-remark",
        ],
    )
    def test_remark_error_means_next_endpoint(self, failed_body: dict) -> None:
        """Failure path: if an endpoint fails, the next one is tried.

        Overpass sends runtime errors and empty answers with HTTP 200, which would
        otherwise read as a country without EGEs. An error remark fails the
        answer even when elements were returned.

        Args:
            failed_body (dict): JSON body of the failed answer.
        """
        failed = _overpass_response(failed_body)
        succeeded = _overpass_response({"elements": [{"type": "node", "id": 1}]})

        with patch("rbc.coordinates.locators.osm_api.requests.post") as mock_post:
            mock_post.side_effect = [failed, succeeded]
            data = post_overpass(query="[out:json];", label="RO")

        assert data == {"elements": [{"type": "node", "id": 1}]}
        assert [call.args[0] for call in mock_post.call_args_list] == OVERPASS_URLS[:2]

    def test_remark_error_from_all_endpoints_returns_none(self) -> None:
        """Failure path: every endpoint reporting a runtime error returns None.

        None (not the empty response) lets the caller retry by relation ID, then fall
        back to its stale cache.
        """
        failed = _overpass_response({"elements": [], "remark": TIMEOUT_REMARK})

        with patch("rbc.coordinates.locators.osm_api.requests.post") as mock_post:
            mock_post.return_value = failed
            data = post_overpass(query="[out:json];", label="RO")

        assert data is None
        assert mock_post.call_count == len(OVERPASS_URLS)

    def test_400_stops_without_trying_other_endpoints(self) -> None:
        """Failure path: a rejected query (HTTP 400) is not retried on other endpoints.

        A syntax error fails on every endpoint, so trying the others only adds load.
        """
        rejected = MagicMock(status_code=400, text="parse error: unknown statement")

        with patch("rbc.coordinates.locators.osm_api.requests.post") as mock_post:
            mock_post.return_value = rejected
            data = post_overpass(query="[out:json];", label="BR")

        assert data is None
        assert mock_post.call_count == 1


# ----------------------------------
# Tests - OverpassLocator (loading & caching)
# ----------------------------------
class TestOverpassLocator:
    """Tests for OverpassLocator's caching, area fallback and once-per-run loads."""

    def test_all_endpoints_failing_uses_stale_cache(self, tmp_path: Path) -> None:
        """Failure path: if every endpoint errors in update mode, the old JSON is used.

        Runs the real post_overpass: the ISO lookup and the relation-ID retry both fail
        on every endpoint, so the stale cache is the only way to avoid "no plants".

        Args:
            tmp_path (Path): Pytest-provided temporary directory, used as `cache_dir`.
        """
        Path(tmp_path, "overpass_BR.json").write_text(
            json.dumps({"elements": [EGE]}), encoding="utf-8"
        )
        failed = _overpass_response({"elements": [], "remark": TIMEOUT_REMARK})

        with patch("rbc.coordinates.locators.osm_api.requests.post") as mock_post:
            mock_post.return_value = failed
            df = OverpassLocator(cache_dir=tmp_path, update=True).get_country_df("BR")

        assert list(df["Name"]) == ["Usina A"]
        assert mock_post.call_count == 2 * len(OVERPASS_URLS)  # ISO + relation lookups

    def test_cached_parquet_skips_overpass(self, tmp_path: Path) -> None:
        """Happy path: an existing parquet is returned without querying Overpass.

        Args:
            tmp_path (Path): Pytest-provided temporary directory, used as `cache_dir`.
        """
        _cached_parquet(tmp_path, name="Cached Plant")

        with patch("rbc.coordinates.locators.osm_api.post_overpass") as mock_post:
            df = OverpassLocator(cache_dir=tmp_path).get_country_df("BR")

        assert list(df["Name"]) == ["Cached Plant"]
        mock_post.assert_not_called()

    def test_update_refetches_and_overwrites(self, tmp_path: Path) -> None:
        """Happy path: update mode ignores the cache, then replaces parquet and JSON.

        Args:
            tmp_path (Path): Pytest-provided temporary directory, used as `cache_dir`.
        """
        parquet_path = _cached_parquet(tmp_path, name="Old Plant")
        response = {"elements": [EGE]}

        with patch("rbc.coordinates.locators.osm_api.post_overpass") as mock_post:
            mock_post.return_value = response
            df = OverpassLocator(cache_dir=tmp_path, update=True).get_country_df("BR")

        assert list(df["Name"]) == ["Usina A"]
        assert list(pd.read_parquet(parquet_path)["Name"]) == ["Usina A"]
        json_path = Path(tmp_path, "overpass_BR.json")
        assert json.loads(json_path.read_text(encoding="utf-8")) == response

    def test_live_reads_and_writes_no_files(self, tmp_path: Path) -> None:
        """Happy path: live mode ignores the cache and leaves `cache_dir` untouched.

        Args:
            tmp_path (Path): Pytest-provided temporary directory, used as `cache_dir`.
        """
        parquet_path = _cached_parquet(tmp_path, name="Old Plant")

        with patch("rbc.coordinates.locators.osm_api.post_overpass") as mock_post:
            mock_post.return_value = {"elements": [EGE]}
            df = OverpassLocator(cache_dir=tmp_path, live=True).get_country_df("BR")

        assert list(df["Name"]) == ["Usina A"]
        assert list(tmp_path.iterdir()) == [parquet_path]
        assert list(pd.read_parquet(parquet_path)["Name"]) == ["Old Plant"]

    def test_failed_iso_lookup_retries_by_relation_id(self) -> None:
        """Failure path: a failed ISO lookup is retried via the country's OSM relation.

        post_overpass returns None when every endpoint failed or answered without
        elements. OSM area IDs are the relation ID + 3600000000 (Brazil: 59470).
        """
        with patch("rbc.coordinates.locators.osm_api.post_overpass") as mock_post:
            mock_post.side_effect = [None, {"elements": [EGE]}]
            df = OverpassLocator().get_country_df("BR")

        assert list(df["Name"]) == ["Usina A"]
        assert "area(3600059470)" in mock_post.call_args_list[1].kwargs["query"]

    @pytest.mark.parametrize(
        "answer, expected_calls",
        [
            pytest.param({"elements": [EGE]}, 1),
            pytest.param(None, 2),  # ISO lookup + relation-ID retry, both failed
        ],
        ids=["successful-load", "failed-load"],
    )
    def test_country_loaded_once_per_run(
        self, answer: dict | None, expected_calls: int
    ) -> None:
        """Happy + failure paths: repeated requests for a country reuse the first load.

        Directories of the same country (e.g. 1h and 15min data, or several bidding
        zones) must not query Overpass again. Failed loads are kept too, so they aren't
        retried.

        Args:
            answer (dict | None): What `post_overpass` returns for every query.
            expected_calls (int): Number of queries the first load needs.
        """
        locator = OverpassLocator()

        with patch("rbc.coordinates.locators.osm_api.post_overpass") as mock_post:
            mock_post.return_value = answer
            first = locator.get_country_df("BR")
            second = locator.get_country_df("br")  # country codes are case-insensitive

        assert second is first
        assert mock_post.call_count == expected_calls


# ----------------------------------
# Tests - _elements_to_df (tag parsing)
# ----------------------------------
class TestElementsToDf:
    """Tests for _elements_to_df's tag parsing (each name variant is a candidate)."""

    def test_one_row_per_name_variant(self) -> None:
        """Happy path: each name and language variant becomes its own row.

        Other "name:*" keys (e.g. "name:etymology") describe the name and are skipped.
        """
        tags = {
            "power": "plant",
            "name": "Usina A",
            "alt_name": "UHE A",
            "name:en": "Plant A",
            "name:zh-Hant": "甲電廠",
            "name:etymology": "Named after river A",
        }
        df = _elements_to_df({"elements": [{**EGE, "tags": tags}]})

        assert set(df["Name"]) == {"Usina A", "UHE A", "Plant A", "甲電廠"}
        assert len(df) == 4
        assert df["OSM_ID"].nunique() == 1

    def test_inactive_prefix_keeps_name_and_sets_status(self) -> None:
        """Happy path: a "was:" EGE keeps its "was:name" and gets status "was"."""
        tags = {"was:power": "plant", "was:name": "Usina Velha"}
        df = _elements_to_df({"elements": [{**EGE, "tags": tags}]})

        assert list(df["Name"]) == ["Usina Velha"]
        assert list(df["Status"]) == ["was"]

    @pytest.mark.parametrize("active_first", [True, False])
    def test_active_tag_wins_over_inactive_twin(self, active_first: bool) -> None:
        """Happy path: an active tag beats its "was:" twin, whichever comes first.

        Args:
            active_first (bool): Whether the active tag precedes the inactive one.
        """
        twins = [("plant:source", "wind"), ("was:plant:source", "coal")]
        tags = {"power": "plant", "name": "Usina A"}
        tags.update(twins if active_first else twins[::-1])
        df = _elements_to_df({"elements": [{**EGE, "tags": tags}]})

        assert list(df["Fueltype"]) == ["wind"]

    def test_unnamed_elements_are_dropped(self) -> None:
        """Failure path: elements without tags or without any name produce no rows."""
        untagged = {"type": "node", "id": 2, "lat": 0.0, "lon": 0.0}
        unnamed = {**untagged, "id": 3, "tags": {"power": "plant"}}
        df = _elements_to_df({"elements": [EGE, untagged, unnamed]})

        assert list(df["Name"]) == ["Usina A"]


# ----------------------------------
# Tests - _parse_coordinates
# ----------------------------------
class TestParseCoordinates:
    """Tests for _parse_coordinates."""

    @pytest.mark.parametrize(
        "element, expected",
        [
            pytest.param({"type": "node", "lat": 44.48, "lon": 28.27}, (44.48, 28.27)),
            pytest.param(
                {"type": "way", "center": {"lat": 45.02, "lon": 24.70}, "nodes": [1]},
                (45.02, 24.70),
            ),
            pytest.param({"type": "relation", "members": []}, (None, None)),
        ],
        ids=["node-own-position", "way-center", "no-coordinates"],
    )
    def test_parse_coordinates(self, element: dict, expected: tuple) -> None:
        """Happy + failure paths: nodes use their own position, ways their `center`.

        Nodes carry `lat` / `lon` themselves, while ways and relations only get a
        `center` from Overpass. Elements with neither return (None, None).

        Args:
            element (dict): OSM element, as Overpass returns it for `out body center;`.
            expected (tuple): Expected (lat, lon).
        """
        assert _parse_coordinates(element) == expected
