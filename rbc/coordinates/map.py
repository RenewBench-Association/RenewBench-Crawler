"""Interactive map visualization for identified EGE locations.

Usage
-----
    from rbc.coordinates.map import build_map

    # Single DataFrame — opens in browser and saves to a directory
    build_map(dfs=[df_coords], name_col="name", fuel_col="fuel_type", output_dir="maps/")

    # Multiple DataFrames with custom labels
    build_map(
        dfs=[df_nl, df_mk], labels=["Netherlands", "North Macedonia"],
        name_col="name", fuel_col="fuel_type"
    )

    # Inside a Jupyter notebook (returns the map object for inline display)
    m = build_map(dfs=[df_coords], name_col="name", fuel_col="fuel_type", open_browser=False)
    m   # displays the map inline
"""

import html as _html
import json
import tempfile
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

import folium
import folium.plugins
import pandas as pd
from loguru import logger

from rbc.coordinates.utils import map_html as tpl

# Browsers that display can display the map without error
BROWSERS = ["safari", "google-chrome", "chrome"]

# ---------------------------------------------------------------------------
# Color mappings (markers, links)
# ---------------------------------------------------------------------------
# Scheme to color by `match_source` value (created by running a pipeline).
_MATCH_SOURCE_COLORS: dict[str, str] = {
    # ppdb (PPM/OSMPP) matches, most to least confident
    "ppdb_direct": "green",  # exact EIC hit in ppdb
    "ppdb_parent_direct": "lightgreen",  # parent EIC → direct ppdb hit
    "ppdb_parent_entsoe_id": "darkgreen",  # fuzzy-resolved parent EIC → ppdb hit
    "ppdb_fuzzy_matrix": "turquoise",  # fuzzy name/fuel match in ppdb
    # GEM (Global Energy Monitor) matches, most to least confident
    "gem_direct": "purple",  # exact EIC hit in GEM
    "gem_parent_direct": "darkpurple",  # parent EIC → direct GEM hit
    "gem_parent_entsoe_id": "pink",  # fuzzy-resolved parent EIC → GEM hit
    "gem_fuzzy_matrix": "beige",  # fuzzy name/fuel match in GEM
    # OSM (Overpass) fallback — direct or fuzzy, both collapse to "osm"
    "osm": "blue",
    # coordinates borrowed from a co-located sibling unit
    "sibling_unit": "orange",
    # no coordinates found (won't normally be plotted)
    "unmatched": "red",
}

# Scheme to color by `<fuel type>` value (if provided by the operators).
_FUELTYPE_COLORS: dict[str, str] = {
    "gas": "orange",
    "natural gas": "orange",
    "coal": "darkgray",
    "hard coal": "darkgray",
    "lignite": "cadetblue",
    "nuclear": "purple",
    "wind": "blue",
    "offshore wind": "darkblue",
    "onshore wind": "blue",
    "solar": "beige",
    "photovoltaic": "beige",
    "hydro": "green",
    "run-of-river": "lightgreen",
    "pumped hydro": "darkgreen",
    "pumped storage": "darkgreen",
    "oil": "red",
    "biomass": "lightgreen",
    "geothermal": "darkred",
    "waste": "gray",
    "other": "lightgray",
    "unknown": "lightgray",
}

# Scheme for cycling through coloring multiple DataFrames without fuel info
_DATASET_COLORS = [
    "blue",
    "red",
    "green",
    "purple",
    "orange",
    "darkblue",
    "darkred",
    "darkgreen",
    "cadetblue",
    "pink",
]

# Columns whose values are rendered as clickable hyperlinks in the popup
_LINK_COL_PATTERNS = {"_url", "_link", "website", "contact:website"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build_map(
    dfs: list[pd.DataFrame],
    name_col: str | None,
    fuel_col: str | None,
    labels: list[str] | None = None,
    output_dir: Path | str | None = None,
    open_browser: bool = True,
    cluster_markers: bool = True,
    tiles: str = "OpenStreetMap",
) -> folium.Map:
    """Build an interactive Leaflet map from a list of coordinate DataFrames.

    When the DataFrames contain a `match_source` column (produced by the ENTSOE enrichment
    pipeline) pin colors reflect the matching strategy used rather than the fuel type, and
    a legend is added to the bottom-right corner. Otherwise, pins are colored by fuel type.

    Each matched EGE is rendered as a clickable pin. Clicking a pin opens a popup table
    that lists every column in the DataFrame — URL-like columns (`osm_url`, `*_url`, …) become
    clickable hyperlinks. When an `osm_geometry` polygon is present it is also drawn as a
    transparent overlay on the map.

    Multiple DataFrames are shown as separate toggleable layers via the built-in
    layer control (top-right corner).

    Args:
        dfs: A list of DataFrames as returned by `<...>Pipeline.run_pipeline()`.
        name_col (str | None): Column header containing EGE names. If None, first col is used.
        fuel_col (str | None): Column header containing EGE fuel types. If None, none exists.
        labels (list): Display name for each DataFrame shown in the layer control.
            Defaults to `["Dataset 1", "Dataset 2", ...]`.
        output_dir (Path | str, optional): Directory to which the created HTML map is saved.
            Defaults to None, where it is stored in the OS temporary dir to be deleted later.
        open_browser (bool, optional): Open the resulting HTML file in the default browser
            immediately after saving. Defaults to `True`.
        cluster_markers (bool, optional): Group nearby markers with `MarkerCluster` when
            zoomed out. Defaults to `True`.
        tiles: Tile provider for the map (e.g. "OpenStreetMap", "CartoDB positron").
            Defaults to "OpenStreetMap".

    Returns:
        folium.Map: The constructed map object. Useful for inline display in
            Jupyter notebooks (just return it as the last expression in a cell).

    Raises:
        ValueError: If `dfs` is empty or `labels` length mismatches `dfs`.
    """
    if not dfs:
        raise ValueError("At least one DataFrame must be supplied.")

    if labels is None:
        labels = [f"Dataset {i + 1}" for i in range(len(dfs))]
    elif len(labels) != len(dfs):
        raise ValueError("`labels` must have the same length as `dfs`.")

    ege_map = _EgeMap(
        dfs,
        labels=labels,
        name_col=name_col,
        fuel_col=fuel_col,
        cluster_markers=cluster_markers,
        tiles=tiles,
    )
    m = ege_map.build()
    ege_map.save_and_display(output_dir, open_browser)
    return m


class _EgeMap:
    """Builds one interactive folium map from one or more EGE coordinate DataFrames.

    Stores the map's per-build state (detected columns, color mode, map itself) that would
    otherwise have to be provided to every popup/marker/legend/sidebar helper separately.

    Attributes:
        dfs: Coordinate DataFrames, one per zone/country/dataset.
        labels: Display label for each entry in `dfs`.
        name_col: Column used as popup header / marker tooltip.
        fuel_col: Column used to color markers when not in match-source mode.
        cluster_markers: Whether to group nearby markers with `MarkerCluster`.
        tiles: Folium tile provider name.
        match_source_col: Detected `match_source` column, or `None` if absent.
        map: The `folium.Map` under construction (set by `build()`).
    """

    def __init__(
        self,
        dfs: list[pd.DataFrame],
        labels: list[str],
        name_col: str | None,
        fuel_col: str | None,
        cluster_markers: bool,
        tiles: str,
    ) -> None:
        """Initialize energy-generating entity (EGE) map creator.

        Args:
            dfs (list[pd.DataFrame]): Coordinate DataFrames.
            labels (list[str]): Display label for each entry in `dfs`.
            name_col (str): Column header containing the EGE name for each DataFrame
                used as the popup header & marker tooltip. If None, the first column is used.
            fuel_col (str | None): Column header of the fuel/energy type for each DataFrame
                used to color the markers. If None, it is assumed none exists.
            cluster_markers (bool): Whether to group nearby markers with `MarkerCluster`.
            tiles (str): Tile provider for creating the folium map (e.g. "OpenStreetMap").
        """
        self.dfs = dfs
        self.labels = labels
        self.name_col = name_col if name_col else self.dfs[0].columns[0]
        self.fuel_col = fuel_col
        self.cluster_markers = cluster_markers
        self.tiles = tiles
        self.map = folium.Map(tiles=self.tiles, zoom_start=4)  # empty map

        self.match_source_col: str | None = None
        for df in self.dfs:
            cols_lower = {c.lower(): c for c in df.columns}
            if "match_source" in df.columns:
                self.match_source_col = cols_lower["match_source"]
            break

        # Bool for whether markers should be colored by match_source rather than fuel type.
        self.use_match_source_colors = self.match_source_col is not None

    # ---------------------------------------------------
    # ENTRY-POINTS
    # ---------------------------------------------------
    def build(self) -> folium.Map:
        """Construct the map, including markers, layer control, legend, sidebar.

        Returns:
            folium.Map: The constructed map object.
        """
        all_lats: list[float] = []
        all_lons: list[float] = []
        for df in self.dfs:
            matched = df.dropna(subset=["lat", "lon"])
            all_lats.extend(matched["lat"].astype(float).tolist())
            all_lons.extend(matched["lon"].astype(float).tolist())

        if not all_lats:
            logger.warning(
                "No EGE coordinates found in any DataFrame. Returning empty map."
            )
            return self.map

        centre = [sum(all_lats) / len(all_lats), sum(all_lons) / len(all_lons)]
        self.map = folium.Map(location=centre, zoom_start=6, tiles=self.tiles)

        if self.use_match_source_colors:
            self._add_markers_by_match_source()
        else:
            self._add_markers_by_fuel()

        folium.LayerControl(collapsed=False).add_to(self.map)
        self._add_legend()
        self._add_sidebar()

        self.map.fit_bounds(
            [[min(all_lats), min(all_lons)], [max(all_lats), max(all_lons)]],
            padding=(30, 30),
        )
        return self.map

    def save_and_display(
        self, output_dir: Path | str | None, open_browser: bool
    ) -> None:
        """Optionally save the built map to disk and optionally open it in a browser.

        Args:
            output_dir (Path | str | None): Directory to save the map to. If None,
                stores only to temporary OS directory to be automatically deleted later.
            open_browser (bool): Whether to open the browser or not.
        """
        if output_dir:
            output_path = Path(output_dir, "map_coordinates.html")
        else:
            output_path = Path(tempfile.gettempdir(), "maps", "map_coordinates.html")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.map.save(str(output_path))
        logger.info(f"Map saved → {output_path}")

        if open_browser:
            open_map_in_browser(output_path)

    # ---------------------------------------------------
    # HTML GEOMETRIES
    # ---------------------------------------------------
    def _popup_html(self, row: pd.Series) -> str:
        """Build the full HTML popup table for a single marker row.

        Args:
            row (pd.Series): Single marker row.

        Returns:
            str: HTML popup table.
        """
        ege_name = (
            str(row[self.name_col])
            if self.name_col and self.name_col in row.index
            else "Power Plant"
        )

        rows_html: list[str] = []
        for col in row.index:
            val = row[col]

            if col == self.name_col:
                continue

            if col == "osm_geometry":
                rows_html.append(tpl.popup_row_html(col, _geometry_summary(val)))
                continue

            if not isinstance(val, (dict, list)) and pd.isna(val):
                continue

            val_str = str(val)
            if _is_link_col(col) and val_str.startswith("http"):
                display = (
                    f"<a href='{val_str}' target='_blank' "
                    f"style='color:#1976d2;text-decoration:none'>&#x1F517; Open</a>"
                )
            else:
                display = val_str if len(val_str) <= 140 else val_str[:137] + "…"

            rows_html.append(tpl.popup_row_html(col, display))

        return tpl.popup_table_html(ege_name, "".join(rows_html))

    def _add_geometry_overlay(self, row: pd.Series, color: str, tooltip: str) -> None:
        """Draw an OSM polygon/polyline on the map when geometry data is present.

        Args:
            row (pd.Series): Single marker row.
            color (str): Name of color for polygon/polyline.
            tooltip (str): Text for tooltip (pop-up box).
        """
        geom = row.get("osm_geometry")
        if geom is None or (isinstance(geom, float) and pd.isna(geom)):
            return
        if isinstance(geom, str):
            try:
                geom = json.loads(geom)
            except (json.JSONDecodeError, ValueError):
                return
        if not isinstance(geom, dict) or geom.get("type") not in (
            "Polygon",
            "LineString",
        ):
            return

        folium.GeoJson(
            data=geom,
            style_function=lambda _, c=color: {
                "color": c,
                "weight": 2,
                "fillOpacity": 0.12,
                "fillColor": c,
            },
            tooltip=tooltip,
        ).add_to(self.map)

    # ---------------------------------------------------
    # HTML MARKERS
    # ---------------------------------------------------
    def _add_markers_by_match_source(self) -> None:
        """Main mode: one global layer per match_source, aggregated across all dfs.

        A single checkbox in the layer control therefore toggles that algorithm's
        pins across every zone, rather than per-country.
        """
        source_to_rows: dict[str, list[pd.Series]] = {}

        for df in self.dfs:
            matched = df.dropna(subset=["lat", "lon"])
            if len(matched) == 0:
                continue

            matched = matched.copy()
            if self.match_source_col and self.match_source_col in matched.columns:
                matched["_ms_key"] = (
                    matched[self.match_source_col].fillna("unmatched").astype(str)
                )
            else:
                matched["_ms_key"] = "unknown"

            for _, row in matched.iterrows():
                source_to_rows.setdefault(str(row["_ms_key"]), []).append(row)

        # Render groups in the canonical order defined by _MATCH_SOURCE_COLORS
        ordered = [s for s in _MATCH_SOURCE_COLORS if s in source_to_rows]
        extras = sorted(s for s in source_to_rows if s not in _MATCH_SOURCE_COLORS)

        total_added = 0
        for source_key in ordered + extras:
            color = _match_source_color(source_key)

            def color_fn(_row: pd.Series) -> str:
                """Function for getting the color for each row element."""
                return color

            added = self._add_marker_layer(
                source_key, source_to_rows[source_key], color_fn
            )
            total_added += added
            logger.info(f"Match-source layer '{source_key}': {added} marker(s).")

        logger.info(
            f"Total: {total_added} markers across {len(source_to_rows)} match-source layer(s)."
        )

    def _add_markers_by_fuel(self) -> None:
        """Fallback mode: one FeatureGroup per dataset, colored by fuel type."""
        n_colors = len(_DATASET_COLORS)
        for idx, (df, label) in enumerate(zip(self.dfs, self.labels)):
            matched = df.dropna(subset=["lat", "lon"])
            if len(matched) == 0:
                logger.info(f"'{label}': No matched rows — layer skipped.")
                continue

            fallback_color = _DATASET_COLORS[idx % n_colors]

            def color_fn(_row: pd.Series) -> str:
                """Function for getting the color for each row element."""
                fueltype = _row.get(self.fuel_col) if self.fuel_col else None
                has_fuel = fueltype is not None and not (
                    isinstance(fueltype, float) and pd.isna(fueltype)
                )
                return _fueltype_color(fueltype) if has_fuel else fallback_color

            rows = [row for _, row in matched.iterrows()]
            self._add_marker_layer(label, rows, color_fn)
            logger.info(
                f"'{label}': added {len(matched)} marker(s) "
                f"({len(df) - len(matched)} unmatched rows omitted)."
            )

    def _add_marker_layer(
        self,
        group_name: str,
        rows: list[pd.Series],
        color_fn: Callable[[pd.Series], str],
    ) -> int:
        """Add one `FeatureGroup` (optionally clustered) of markers to the map.

        Shared by both coloring modes: `color_fn` is a constant lookup in
        match-source mode, and a per-row fuel-type lookup in legacy mode.

        Args:
            group_name: Name shown for this layer in the folium `LayerControl`.
            rows: DataFrame rows (each must have valid `lat`/`lon`) to render.
            color_fn: Called per row to pick its marker/overlay color.

        Returns:
            int: Number of markers added.
        """
        fg = folium.FeatureGroup(name=group_name, show=True)
        cluster = folium.plugins.MarkerCluster() if self.cluster_markers else None
        target: folium.FeatureGroup | folium.plugins.MarkerCluster = cluster or fg

        for row in rows:
            color = color_fn(row)
            lat, lon = float(row["lat"]), float(row["lon"])
            tooltip_text = (
                str(row[self.name_col])
                if self.name_col and self.name_col in row.index
                else ""
            )

            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(self._popup_html(row), max_width=460),
                tooltip=tooltip_text,
                icon=folium.Icon(color=color, icon="bolt", prefix="fa"),
            ).add_to(target)
            self._add_geometry_overlay(row, color, tooltip_text)

        if cluster is not None:
            cluster.add_to(fg)

        fg.add_to(self.map)
        return len(rows)

    # ---------------------------------------------------
    # HTML LEGEND / SIDEBAR
    # ---------------------------------------------------
    def _add_legend(self) -> None:
        """Inject the match-source legend, when that coloring mode is active."""
        if not self.use_match_source_colors:
            return

        present_sources: dict[str, str] = {}
        for df in self.dfs:
            if self.match_source_col and self.match_source_col in df.columns:
                for val in df[self.match_source_col].dropna().unique():
                    key = str(val).strip().lower()
                    present_sources.setdefault(key, _match_source_color(key))

        if present_sources:
            self.map.get_root().html.add_child(
                folium.Element(tpl.legend_html(present_sources))
            )

    def _add_sidebar(self) -> None:
        """Insert a sidebar for all unmatched plants (extracted from NaN lat/lon rows)."""
        sections: list[str] = []
        total_unmatched = 0

        for df, label in zip(self.dfs, self.labels):
            if "lat" not in df.columns or "lon" not in df.columns:
                unmatched = df
            else:
                unmatched = df[df["lat"].isna() | df["lon"].isna()]

            if len(unmatched) == 0:
                continue

            total_unmatched += len(unmatched)
            items: list[str] = []
            for _, row in unmatched.iterrows():
                name = _html.escape(
                    str(row[self.name_col])
                    if self.name_col and self.name_col in row.index
                    else "—"
                )
                fuel = None
                if self.fuel_col and self.fuel_col in row.index:
                    fval = row[self.fuel_col]
                    if fval is not None and not (
                        isinstance(fval, float) and pd.isna(fval)
                    ):
                        fuel = _html.escape(str(fval).strip())

                items.append(tpl.sidebar_item_html(name, fuel))

            sections.append(
                tpl.sidebar_section_html(
                    _html.escape(label), len(unmatched), "".join(items)
                )
            )

        if not sections:
            return

        html = tpl.sidebar_html(total_unmatched, len(sections), "\n".join(sections))
        self.map.get_root().html.add_child(folium.Element(html))


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def _match_source_color(source: Any) -> str:
    """Find a color for a folium marker depending on a given `match_source` value.

    Args:
        source (Any): match_source value.

    Returns:
        str: Color defined by `match_source` value. Defaults to "lightgray".
    """
    if source is None or (isinstance(source, float) and pd.isna(source)):
        return "lightgray"
    return _MATCH_SOURCE_COLORS.get(str(source).strip().lower(), "lightgray")


def _fueltype_color(fueltype: Any) -> str:
    """Find a color for a folium marker depending on a given fuel type value.

    Args:
        fueltype (Any): Fuel type value.

    Returns:
        str: Color defined by fuel type value. Defaults to "lightgray".
    """
    if fueltype is None or (isinstance(fueltype, float) and pd.isna(fueltype)):
        return "lightgray"

    key = str(fueltype).strip().lower()
    for fragment, color in _FUELTYPE_COLORS.items():
        if fragment in key:
            return color
    return "lightgray"


def _geometry_summary(geom: Any) -> str:
    """Provide a short, human-readable description of an ``osm_geometry`` value.

    Args:
        geom (Any): GeoJSON geometry value to be described.

    Returns:
        str: Description of the ``osm_geometry`` value.
    """
    if geom is None or (isinstance(geom, float) and pd.isna(geom)):
        return "—"

    if isinstance(geom, str):
        try:
            geom = json.loads(geom)
        except (json.JSONDecodeError, ValueError):
            return str(geom)[:60]

    if isinstance(geom, dict):
        gtype = geom.get("type", "?")
        coords = geom.get("coordinates", [])
        if gtype == "Polygon" and coords:
            return f"Polygon ({len(coords[0])} pts)"
        if gtype == "Point" and len(coords) >= 2:
            return f"Point ({coords[0]:.5f}, {coords[1]:.5f})"
        return gtype

    return "—"


def _is_link_col(col: str) -> bool:
    """Check if the column name contains a link (URL).

    Args:
        col (str): The column name to check.

    Returns:
        bool: True if the column name suggests it holds a URL.
    """
    col_l = col.lower()
    return any(col_l.endswith(p) or col_l == p.lstrip("_") for p in _LINK_COL_PATTERNS)


def open_map_in_browser(file_path: Path | str) -> None:
    """Open a map in browser.

    Args:
        file_path (Path | str): Path to the map file.
    """
    uri = Path(file_path).as_uri()

    controller = None
    for name in BROWSERS:
        try:
            controller = webbrowser.get(name)
            break
        except webbrowser.Error:
            continue

    if controller:
        controller.open(uri)
    else:
        webbrowser.open(uri)  # fallback
