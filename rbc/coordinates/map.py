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
from collections import Counter
from pathlib import Path
from typing import Any

import folium
import folium.plugins
import pandas as pd
from loguru import logger

from rbc.coordinates.utils import map_html as tpl
from rbc.coordinates.utils.values import is_missing, strip_lower_str, strip_str

BROWSERS = ["safari", "google-chrome", "chrome"]  # browsers that display without error

# ---------------------------------------------------------------------------
# Marker plotting schemas (color & icon types)
# ---------------------------------------------------------------------------
# Define marker color by `match_source` value (created by running a pipeline).
_MATCH_SOURCE_COLORS: dict[str, str] = {
    # GEM (Global Energy Monitor) matches, most to least confident
    "gem_direct": "purple",  # exact EIC hit in GEM
    "gem_parent_direct": "darkpurple",  # parent EIC → direct GEM hit
    "gem_parent_entsoe_id": "pink",  # fuzzy-resolved parent EIC → GEM hit
    "gem_fuzzy": "beige",  # fuzzy name/fuel match in GEM
    # ppdb (PPM/OSMPP) matches, most to least confident
    "ppdb_direct": "green",  # exact EIC hit in ppdb
    "ppdb_parent_direct": "lightgreen",  # parent EIC → direct ppdb hit
    "ppdb_parent_entsoe_id": "darkgreen",  # fuzzy-resolved parent EIC → ppdb hit
    "ppdb_fuzzy": "cadetblue",  # fuzzy name/fuel match in ppdb
    # OSM (Overpass) matches
    "osm_fuzzy": "darkblue",
    # coordinates borrowed from a sibling unit
    "gem_sibling": "coral",
    "ppdb_sibling": "orange",
    "osm_sibling": "tan",
    # no coordinates found (won't normally be plotted)
    "unmatched": "red",
}
_DEFAULT_COLOR = "lightgray"

# Define marker icon by fuel type (given by the operator)
_FUEL_ICONS: dict[str, str] = {
    # Renewables
    "solar": "sun",
    "photovoltaic": "sun",
    "wind": "wind",
    # Hydro
    "hydro": "water",
    "run-of-river": "water",
    "pumped hydro": "water",
    "pumped storage": "water",
    # Biomass
    "biomass": "leaf",
    "peat": "leaf",
    # Geothermal
    "geothermal": "volcano",
    # Fossil fuels
    "gas": "fire",
    "natural gas": "fire",
    "coal": "fire",
    "hard coal": "fire",
    "lignite": "fire",
    "thermal": "fire",
    "oil": "fire",
    # Nuclear & waste
    "nuclear": "radiation",
    "waste": "trash",
}
_DEFAULT_ICON = "bolt"


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
    that lists every column in the DataFrame — URL-like columns (`OSM_URL`, `*_url`, …) become
    clickable hyperlinks. When an `osm.geometry` polygon is present it is also drawn as a
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

        Raises:
            ValueError: If not all `dfs` contain the name column `name_col`.
        """
        self.dfs = dfs
        self.labels = labels
        self.name_col = name_col if name_col else self.dfs[0].columns[0]
        self.fuel_col = fuel_col
        self.cluster_markers = cluster_markers
        self.tiles = tiles
        self.map = folium.Map(tiles=self.tiles, zoom_start=4)  # empty map

        if not all(self.name_col in df for df in dfs):
            raise ValueError(
                f"Not all dfs contain the same name column `{self.name_col}`!"
            )

        if not self.fuel_col:
            logger.warning("No `fuel_col` provided. Cannot define icons by fuel type.")
        elif self.fuel_col and not all(self.fuel_col in df for df in dfs):
            logger.warning(
                f"Not all dfs contain the same fuel column '{self.fuel_col}'! "
                f"Cannot define icons by fuel type."
            )
            self.fuel_col = None

        self.match_source_col: str | None = "match_source"
        if not all(self.match_source_col in df for df in dfs):
            logger.warning(
                "Not all dfs contain a `match_source` column (inserted by coordinate"
                "/location finding)! Cannot group/color markers by matching strategy."
            )
            self.match_source_col = None

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
        self._add_markers()

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
    # MARKERS & THEIR HELPERS
    # ---------------------------------------------------
    def _add_markers(self) -> None:
        """Add EGE locations as global layers per match_source algorithm.

        A single checkbox in the layer control can toggle that algorithm's markers. The
        markers are additionally colored by the match_source algorithm. The icons are
        defined by the EGE's fuel type (where its known).
        """
        # Build a dict of the used match_source algorithms and the associated data rows
        ms_groups: dict[str, list[pd.Series]] = {}

        for df in self.dfs:
            matched = df.dropna(subset=["lat", "lon"])
            if len(matched) == 0:
                continue

            for _, row in matched.iterrows():
                ms_algorithm = (
                    strip_str(row[self.match_source_col]) or "unknown"
                    if self.match_source_col
                    else "unknown"
                )
                ms_groups.setdefault(ms_algorithm, []).append(row)

        # Render groups in the canonical order defined by _MATCH_SOURCE_COLORS
        groups_ordered = [s for s in _MATCH_SOURCE_COLORS if s in ms_groups]
        groups_extras = sorted(s for s in ms_groups if s not in _MATCH_SOURCE_COLORS)

        total_added = 0
        for ms_algorithm in groups_ordered + groups_extras:
            rows = ms_groups[ms_algorithm]
            color = _match_source_color(ms_algorithm)

            fg = folium.FeatureGroup(name=ms_algorithm, show=True)
            cluster = folium.plugins.MarkerCluster() if self.cluster_markers else None
            target: folium.FeatureGroup | folium.plugins.MarkerCluster = cluster or fg

            for row in rows:
                tooltip_text = str(row[self.name_col])
                icon = _fueltype_icon(row.get(self.fuel_col, None))

                lat, lon = float(row["lat"]), float(row["lon"])

                folium.Marker(
                    location=[lat, lon],
                    popup=folium.Popup(self._build_popup_html(row), max_width=460),
                    tooltip=tooltip_text,
                    icon=folium.Icon(color=color, icon=icon, prefix="fa"),
                ).add_to(target)
                self._add_geometry_overlay(row, color, tooltip_text)

            if cluster is not None:
                cluster.add_to(fg)

            fg.add_to(self.map)
            added = len(rows)
            total_added += added

            logger.info(f"Match-source layer '{ms_algorithm}': {added} marker(s).")

        logger.info(
            f"Total: {total_added} markers across {len(ms_groups)} match-source layer(s)."
        )

    def _build_popup_html(self, row: pd.Series) -> str:
        """Build the full HTML popup table for a single marker row.

        Args:
            row (pd.Series): Single marker row.

        Returns:
            str: HTML popup table.
        """
        ege_name = str(row[self.name_col])

        rows_html: list[str] = []
        for col in row.index:
            val = row[col]

            if col == self.name_col:
                continue

            if col == "osm.geometry":
                rows_html.append(tpl.popup_row_html(col, _geometry_summary(val)))
                continue

            if is_missing(val):
                continue

            # define how row values are displayed (simple values as is or links as href)
            val_str = str(val)
            col_str = col.lower()
            col_is_link = any(
                col_str.endswith(p) or col_str == p.lstrip("_")
                for p in {".url", "_url"}
            )
            if col_is_link and val_str.startswith("http"):
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
        geom = row.get("osm.geometry")
        if is_missing(geom):
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
    # LEGEND AND SIDEBAR
    # ---------------------------------------------------
    def _add_legend(self) -> None:
        """Add the color (`self.match_source_col`) and icon (`self.fuel_col`) legends."""
        algo_colors: dict[str, str] = {}
        fuel_icons: dict[str, str] = {}
        fallback = pd.Series("unknown", dtype=object)

        algo_counts: Counter[str] = Counter()
        fuel_counts: Counter[str] = Counter()

        for df in self.dfs:
            # tally match source algorithms
            for val in df.get(self.match_source_col, fallback).dropna().unique():
                algo_colors.setdefault(strip_lower_str(val), _match_source_color(val))

            algo_counts.update(
                df.get(self.match_source_col, fallback).dropna().map(strip_lower_str)
            )

            # tally fueltypes
            for val in df.get(self.fuel_col, fallback).dropna().unique():
                fuel_icons.setdefault(strip_lower_str(val), _fueltype_icon(val))

            fuel_counts.update(
                df.get(self.fuel_col, fallback).dropna().map(strip_lower_str)
            )

        # Format "key"/"k" as "label (count)"
        used_algos = {
            f"{k} ({algo_counts[k]})": color for k, color in algo_colors.items()
        }
        used_fuels = {f"{k} ({fuel_counts[k]})": icon for k, icon in fuel_icons.items()}

        panels = []
        if used_algos:
            panels.append(tpl.color_legend_panel(used_algos))
        if used_fuels:
            panels.append(tpl.icon_legend_panel(used_fuels))

        if panels:
            legend_html = tpl.legend_html(panels)
            self.map.get_root().html.add_child(folium.Element(legend_html))

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
                name = _html.escape(str(row[self.name_col]))
                fuel = None

                if self.fuel_col:
                    f = strip_str(row[self.fuel_col])
                    if f:
                        fuel = _html.escape(f)

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
        str: Color defined by `match_source` value. Defaults to _DEFAULT_COLOR ("lightgray").
    """
    return _MATCH_SOURCE_COLORS.get(strip_lower_str(source), _DEFAULT_COLOR)


def _fueltype_icon(fueltype: Any) -> str:
    """Find an icon for a folium marker depending on a given fuel type value.

    Args:
        fueltype (Any): Fuel type value.

    Returns:
        str: Icon defined by fuel type value. Defaults to _DEFAULT_ICON ("bolt").
    """
    key = strip_lower_str(fueltype)
    if not key:
        return _DEFAULT_ICON

    for fragment, icon in _FUEL_ICONS.items():
        if fragment in key:
            return icon
    return _DEFAULT_ICON


def _geometry_summary(geom: Any) -> str:
    """Provide a short, human-readable description of an ``osm.geometry`` value.

    Args:
        geom (Any): GeoJSON geometry value to be described.

    Returns:
        str: Description of the ``osm.geometry`` value.
    """
    if is_missing(geom):
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
