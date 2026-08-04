# tests/coordinates/test_map.py
"""Tests for the map-building central function, class and helper functions."""

from pathlib import Path
from typing import Callable

import folium
import pandas as pd
import pytest

from rbc.coordinates.map import (
    _DEFAULT_COLOR,
    _DEFAULT_ICON,
    _EgeMap,
    _fueltype_icon,
    _geometry_summary,
    _match_source_color,
    build_map,
)


# ----------------------------------
# Test helpers
# ----------------------------------
def _markers_by_layer(m: folium.Map) -> dict[str, list[folium.Marker]]:
    """Group every `folium.Marker` in `m` by its parent FeatureGroup's layer name.

    Args:
        m (folium.Map): A built map (assumes `cluster_markers=False`).

    Returns:
        dict[str, list[folium.Marker]]: Markers, keyed by FeatureGroup `layer_name`.
    """
    return {
        child.layer_name: [
            c for c in child._children.values() if isinstance(c, folium.Marker)
        ]
        for child in m._children.values()
        if isinstance(child, folium.FeatureGroup)
    }


def _marker_attributes(marker: folium.Marker) -> dict:
    """Get a `folium.Marker`'s attribs (folium.Icon options) dict (marker_color, icon, ...).

    Args:
        marker (folium.Marker): The marker to inspect.

    Returns:
        dict: The marker's `folium.Icon` options, or `{}` if it has none.
    """
    for child in marker._children.values():
        if isinstance(child, folium.map.Icon):
            return child.options
    return {}


# ----------------------------------
# Fixtures
# ----------------------------------
@pytest.fixture
def df_matched() -> pd.DataFrame:
    """Two matched EGEs (different match_source/fuel type) and one unmatched.

    Returns:
        pd.DataFrame: Synthetic coordinate df resembling one pipeline's output.
    """
    return pd.DataFrame(
        [
            {
                "name": "Plant A",
                "lat": 52.1,
                "lon": 4.1,
                "fuel_type": "Onshore Wind",
                "match_source": "osm",
            },
            {
                "name": "Plant B",
                "lat": 52.2,
                "lon": 4.3,
                "fuel_type": "Solar",
                "match_source": "gem_direct",
            },
            {
                "name": "Plant C (unmatched)",
                "lat": None,
                "lon": None,
                "fuel_type": "Gas",
                "match_source": None,
            },
        ]
    )


@pytest.fixture
def make_ege_map() -> Callable[..., _EgeMap]:
    """Factory fixture for building `_EgeMap` instances with concise defaults.

    Returns:
        Callable[..., _EgeMap]: Factory taking `dfs` plus any `_EgeMap` kwarg overrides.
    """

    def _factory(
        dfs: list[pd.DataFrame],
        name_col: str | None = "name",
        fuel_col: str | None = None,
        labels: list[str] | None = None,
        cluster_markers: bool = False,
    ) -> _EgeMap:
        """Build one `_EgeMap` instance for a test, with sensible defaults filled in.

        Args:
            dfs (list[pd.DataFrame]): Coordinate DataFrames to build the map from.
            name_col (str | None): Column header containing EGE names. Defaults to "name".
            fuel_col (str | None): Column header containing EGE fuel types. Defaults to None.
            labels (list[str] | None): Display label per df. Defaults to `["L0", "L1", ...]`.
            cluster_markers (bool): Whether to cluster markers. Defaults to False (so
                markers are directly reachable via `_markers_by_layer`).

        Returns:
            _EgeMap: The constructed (not yet built) `_EgeMap` instance.
        """
        return _EgeMap(
            dfs,
            labels=labels or [f"L{i}" for i in range(len(dfs))],
            name_col=name_col,
            fuel_col=fuel_col,
            cluster_markers=cluster_markers,
            tiles="OpenStreetMap",
        )

    return _factory


# ----------------------------------
# Tests
# ----------------------------------
class TestBuildMap:
    """Tests for the central map-building central function."""

    def test_build_map(self, df_matched: pd.DataFrame) -> None:
        """Happy path: minimum inputs (no `labels`, output_dir) still builds a map.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
        """
        m = build_map(
            [df_matched, df_matched],
            name_col="name",
            fuel_col="fuel_type",
            open_browser=False,
        )
        assert isinstance(m, folium.Map)

    def test_build_map_with_saving(
        self, df_matched: pd.DataFrame, tmp_path: Path
    ) -> None:
        """Happy path: the built map is saved as `map_coordinates.html` in `output_dir`.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            tmp_path (Path): Pytest-provided temporary directory.
        """
        build_map(
            [df_matched],
            name_col="name",
            fuel_col="fuel_type",
            output_dir=tmp_path,
            open_browser=False,
        )
        assert Path(tmp_path, "map_coordinates.html").exists()

    def test_build_map_error_empty_dfs(self) -> None:
        """Failure path: an empty `dfs` list raises ValueError."""
        with pytest.raises(ValueError, match="At least one DataFrame"):
            build_map([], name_col="name", fuel_col=None)

    def test_build_map_error_label_mismatch(self, df_matched: pd.DataFrame) -> None:
        """Failure path: `labels` must have the same length as `dfs`.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
        """
        with pytest.raises(ValueError, match="same length"):
            build_map([df_matched], name_col="name", fuel_col=None, labels=["a", "b"])


class TestEGEMapInit:
    """Tests for the EGE map class' initialization and entry point methods."""

    def test_init_name_col_default(
        self, df_matched: pd.DataFrame, make_ege_map: Callable
    ) -> None:
        """Happy path: `name_col=None` falls back to `dfs[0]`'s first column.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        ege_map = make_ege_map([df_matched], name_col=None)
        assert ege_map.name_col == df_matched.columns[0]

    def test_init_error_missing_name_col(
        self, df_matched: pd.DataFrame, make_ege_map: Callable
    ) -> None:
        """Failure path: raises ValueError when any df lacks the resolved `name_col`.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        other = pd.DataFrame({"different_col": ["X"], "lat": [1.0], "lon": [1.0]})
        with pytest.raises(ValueError, match="name column"):
            make_ege_map([df_matched, other], name_col="name")

    def test_init_fuel_col_default(
        self, df_matched: pd.DataFrame, make_ege_map: Callable
    ) -> None:
        """Happy path: `fuel_col` stays `None` (no icon-by-fuel) when not provided.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        ege_map = make_ege_map([df_matched], fuel_col=None)
        assert ege_map.fuel_col is None

    def test_init_fuel_col_reset(
        self, df_matched: pd.DataFrame, make_ege_map: Callable
    ) -> None:
        """Failure-tolerant path: `fuel_col` resets to `None` if any df lacks it.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        other = pd.DataFrame({"name": ["X"], "lat": [1.0], "lon": [1.0]})
        ege_map = make_ege_map([df_matched, other], fuel_col="fuel_type")
        assert ege_map.fuel_col is None

    def test_init_match_source_col_default(
        self, df_matched: pd.DataFrame, make_ege_map: Callable
    ) -> None:
        """Happy path: `match_source_col` is `"match_source"` when every df has it.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        ege_map = make_ege_map([df_matched])
        assert ege_map.match_source_col == "match_source"

    def test_init_match_source_col_reset(
        self, df_matched: pd.DataFrame, make_ege_map: Callable
    ) -> None:
        """Failure-tolerant path: `match_source_col` resets to `None` if any df lacks it.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        other = pd.DataFrame({"name": ["X"], "lat": [1.0], "lon": [1.0]})
        ege_map = make_ege_map([df_matched, other])
        assert ege_map.match_source_col is None

    def test_build(self, df_matched: pd.DataFrame, make_ege_map: Callable) -> None:
        """Happy path: `build()` returns full map.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        ege_map = make_ege_map([df_matched])
        m = ege_map.build()
        assert isinstance(m, folium.Map)
        assert any(isinstance(c, folium.FeatureGroup) for c in m._children.values())

    def test_build_empty_map(self, make_ege_map: Callable) -> None:
        """Failure path: `build()` returns an (empty) map when no row has coordinates.

        Args:
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        df = pd.DataFrame({"name": ["X"], "lat": [None], "lon": [None]})
        ege_map = make_ege_map([df])
        m = ege_map.build()
        assert isinstance(m, folium.Map)
        assert not any(isinstance(c, folium.FeatureGroup) for c in m._children.values())


class TestEGEMapMarkers:
    """Tests for the EGE map class' marker and helper methods."""

    def test_add_markers(
        self, df_matched: pd.DataFrame, make_ege_map: Callable
    ) -> None:
        """Happy path: matched rows land in one FeatureGroup, unmatched are excluded.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        ege_map = make_ege_map([df_matched], fuel_col="fuel_type")
        m = ege_map.build()

        # check that the different layers are built depending on match_source_col
        by_layer = _markers_by_layer(m)
        assert set(by_layer) == {"osm", "gem_direct"}
        assert len(by_layer["osm"]) == 1
        assert len(by_layer["gem_direct"]) == 1

        # check that markers color and icon depending on match_source_col and fuel_col
        osm_marker = by_layer["osm"][0]
        osm_attributes = _marker_attributes(osm_marker)
        assert osm_attributes["marker_color"] == _match_source_color("osm")
        assert osm_attributes["icon"] == _fueltype_icon("Onshore Wind")

        # check that unmatched rows (no lat/lon) are excluded - here: Plant C
        total_markers = sum(len(v) for v in _markers_by_layer(m).values())
        assert total_markers == 2

    def test_add_markers_no_match_source_col(self, make_ege_map: Callable) -> None:
        """Failure-tolerant: markers in default color & unknown layer without match_source.

        Args:
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        df = pd.DataFrame({"name": ["A", "B"], "lat": [1.0, 2.0], "lon": [1.0, 2.0]})
        ege_map = make_ege_map([df])
        m = ege_map.build()

        by_layer = _markers_by_layer(m)
        assert set(by_layer) == {"unknown"}

        unknown_marker = by_layer["unknown"][0]
        unknown_attributes = _marker_attributes(unknown_marker)
        assert unknown_attributes["marker_color"] == _DEFAULT_COLOR

    def test_add_markers_no_fuel_col(
        self, df_matched: pd.DataFrame, make_ege_map: Callable
    ) -> None:
        """Happy path: markers use the default icon when `fuel_col` is not provided.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        ege_map = make_ege_map([df_matched], fuel_col=None)
        m = ege_map.build()

        (osm_marker,) = _markers_by_layer(m)["osm"]
        assert _marker_attributes(osm_marker)["icon"] == _DEFAULT_ICON

    def test_build_popup_html(
        self, df_matched: pd.DataFrame, make_ege_map: Callable
    ) -> None:
        """Happy path: the EGE name is the popup header, not duplicated as a table row.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        ege_map = make_ege_map([df_matched])
        row = df_matched.iloc[0]

        html = ege_map._build_popup_html(row)

        assert "Plant A" in html
        assert html.count("Plant A") == 1  # only the header, not a "name" row too

    def test_add_geometry_overlay(self, make_ege_map: Callable) -> None:
        """Happy path: a valid Polygon geometry is drawn as a GeoJson overlay.

        Args:
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        df = pd.DataFrame({"name": ["A"], "lat": [1.0], "lon": [1.0]})
        ege_map = make_ege_map([df])
        row = pd.Series(
            {"osm_geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}}
        )

        ege_map._add_geometry_overlay(row, color="blue", tooltip="tip")

        assert any(
            isinstance(c, folium.GeoJson) for c in ege_map.map._children.values()
        )

    def test_add_geometry_overlay_skipped_when_missing(
        self, make_ege_map: Callable
    ) -> None:
        """Failure path: no overlay is added when `osm_geometry` is missing.

        Args:
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        df = pd.DataFrame({"name": ["A"], "lat": [1.0], "lon": [1.0]})
        ege_map = make_ege_map([df])
        row = pd.Series({"name": "A"})

        ege_map._add_geometry_overlay(row, color="blue", tooltip="tip")

        assert not any(
            isinstance(c, folium.GeoJson) for c in ege_map.map._children.values()
        )


class TestEGEMapLegendSidebar:
    """Tests for the EGE map class' legend and sidebar methods."""

    def test_add_legend_deduplicates_collapsed(self, make_ege_map: Callable) -> None:
        """Happy path: legend correctly added, with duplicates collapsed into one entry.

        Args:
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        df = pd.DataFrame(
            {
                "name": ["A", "B"],
                "lat": [1.0, 2.0],
                "lon": [1.0, 2.0],
                "fuel_type": ["Wind", "wind"],
                "match_source": ["osm", "osm"],
            }
        )
        ege_map = make_ege_map([df], fuel_col="fuel_type")
        m = ege_map.build()

        html = m.get_root().render()
        assert html.count("fa-wind") == 1

    def test_add_legend_unknown_fallback_shown(self, make_ege_map: Callable) -> None:
        """Happy path: legend still correctly adds an 'unknown' entry without match_source.

        Args:
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        df = pd.DataFrame({"name": ["A"], "lat": [1.0], "lon": [1.0]})
        ege_map = make_ege_map([df])
        m = ege_map.build()

        html = m.get_root().render()
        assert "unknown" in html

    def test_add_sidebar(
        self, df_matched: pd.DataFrame, make_ege_map: Callable
    ) -> None:
        """Happy path: unmatched rows appear in the sidebar, including their fuel type.

        Args:
            df_matched (pd.DataFrame): Location finding df with matched/unmatched EGE rows.
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        ege_map = make_ege_map([df_matched], fuel_col="fuel_type")
        m = ege_map.build()

        html = m.get_root().render()
        assert "Plant C (unmatched)" in html
        assert "Unmatched (1)" in html
        assert "Gas" in html

    def test_add_sidebar_none_when_all_is_matched(self, make_ege_map: Callable) -> None:
        """Happy path: no sidebar is injected when every row has coordinates.

        Args:
            make_ege_map (Callable): Factory fixture for `_EgeMap`.
        """
        df = pd.DataFrame({"name": ["A"], "lat": [1.0], "lon": [1.0]})
        ege_map = make_ege_map([df])
        m = ege_map.build()

        assert "rbc-sidebar" not in m.get_root().render()


class TestHelpers:
    """Tests for the helper functions."""

    @pytest.mark.parametrize(
        "source, expected",
        [
            ("osm", "darkblue"),
            ("OSM", "darkblue"),  # case-insensitive
            ("  gem_direct  ", "purple"),  # stripped
            ("totally_unknown_algorithm", _DEFAULT_COLOR),
            (None, _DEFAULT_COLOR),
            (float("nan"), _DEFAULT_COLOR),
        ],
    )
    def test_match_source_color(
        self, source: str | float | None, expected: str
    ) -> None:
        """Happy + failure paths: Known/unknown/missing match_source values handled correctly.

        Args:
            source (str | float | None): Parametrized `match_source` value under test.
            expected (str): Expected color returned by `_match_source_color`.
        """
        assert _match_source_color(source) == expected

    @pytest.mark.parametrize(
        "fueltype, expected",
        [
            ("Solar", "sun"),
            ("Onshore Wind", "wind"),
            ("  PUMPED STORAGE  ", "water"),
            ("totally_unknown_fuel", _DEFAULT_ICON),
            (None, _DEFAULT_ICON),
            (float("nan"), _DEFAULT_ICON),
        ],
    )
    def test_fueltype_icon(self, fueltype: str | float | None, expected: str) -> None:
        """Happy + failure paths: Known/unknown/missing fuel type values handled correctly.

        Args:
            fueltype (str | float | None): Parametrized fuel type value under test.
            expected (str): Expected icon name returned by `_fueltype_icon`.
        """
        assert _fueltype_icon(fueltype) == expected

    @pytest.mark.parametrize(
        "geom, expected",
        [
            (None, "—"),
            (float("nan"), "—"),
            (
                {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]},
                "Polygon (3 pts)",
            ),
            (
                {"type": "Point", "coordinates": [4.1, 52.2]},
                "Point (4.10000, 52.20000)",
            ),
            (
                '{"type": "Point", "coordinates": [1.0, 2.0]}',
                "Point (1.00000, 2.00000)",
            ),
            ("not valid json", "not valid json"),
        ],
    )
    def test_geometry_summary(
        self, geom: dict | str | float | None, expected: str
    ) -> None:
        """Happy + failure paths: dict/JSON-string/invalid/missing geometry values handled.

        Args:
            geom (dict | str | float | None): Parametrized `osm_geometry` value under test.
            expected (str): Expected human-readable summary from `_geometry_summary`.
        """
        assert _geometry_summary(geom) == expected
