"""Interactive map visualisation for power plant coordinate data.

Usage
-----
    from rbc.coordinates.map import build_map

    # Single DataFrame — opens in browser
    build_map(df_coords)

    # Multiple DataFrames with custom labels
    build_map([df_nl, df_mk], labels=["Netherlands", "North Macedonia"])

    # Save without opening browser
    build_map(df_coords, output_path="plants.html", open_browser=False)

    # Inside a Jupyter notebook (returns the map object for inline display)
    m = build_map(df_coords, open_browser=False)
    m   # displays the map inline
"""

from __future__ import annotations

import html as _html
import json
import tempfile
import webbrowser
from pathlib import Path
from typing import Any

import folium
import folium.plugins
import pandas as pd
from loguru import logger

# ---------------------------------------------------------------------------
# Marker colour mapping by match_source
# ---------------------------------------------------------------------------

#: One folium colour per ``match_source`` value produced by the ENTSOE pipeline.
#: The values must be valid Leaflet/folium colour names.
_MATCH_SOURCE_COLORS: dict[str, str] = {
    "ppm_direct": "green",  # exact ENTSOE-ID hit in powerplantmatching
    "ppm_parent_direct": "lightgreen",  # parent EicParent field → direct PPM hit
    "ppm_parent_entsoe_id": "darkgreen",  # fuzzy-resolved parent EIC → PPM hit
    "ppm_fuzzy_name": "orange",  # fuzzy plant-name match in PPM
    "osm": "blue",  # OpenInfraMap / Overpass fallback
    "unmatched": "lightgray",  # no coordinates (won't normally be plotted)
}

_MATCH_SOURCE_DEFAULT_COLOR = "lightgray"


def _match_source_color(source: Any) -> str:
    """Return a folium marker colour for a given ``match_source`` value."""
    if source is None or (isinstance(source, float) and pd.isna(source)):
        return _MATCH_SOURCE_DEFAULT_COLOR
    return _MATCH_SOURCE_COLORS.get(
        str(source).strip().lower(), _MATCH_SOURCE_DEFAULT_COLOR
    )


# ---------------------------------------------------------------------------
# Marker colour mapping by fuel type
# ---------------------------------------------------------------------------

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

# Cycle through these when colouring multiple DataFrames without fuel info
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


def _fueltype_color(fueltype: Any) -> str:
    """Return a folium marker colour string for a given fuel type value."""
    if fueltype is None or (isinstance(fueltype, float) and pd.isna(fueltype)):
        return "lightgray"
    key = str(fueltype).strip().lower()
    for fragment, color in _FUELTYPE_COLORS.items():
        if fragment in key:
            return color
    return "lightgray"


# ---------------------------------------------------------------------------
# Popup HTML builder
# ---------------------------------------------------------------------------


def _geometry_summary(geom: Any) -> str:
    """Return a short human-readable description of an ``osm_geometry`` value."""
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
    """Return True if the column name suggests it holds a URL."""
    col_lower = col.lower()
    return any(
        col_lower.endswith(p) or col_lower == p.lstrip("_") for p in _LINK_COL_PATTERNS
    )


def _popup_html(row: pd.Series, name_col: str | None = None) -> str:
    """Build the full HTML popup table for a single marker row.

    Args:
        row: A single row of the coordinates DataFrame.
        name_col: Column that contains the plant name (used as popup header).

    Returns:
        str: Self-contained HTML string for use in a ``folium.Popup``.
    """
    plant_name = (
        str(row[name_col]) if name_col and name_col in row.index else "Power Plant"
    )

    rows_html: list[str] = []
    for col in row.index:
        val = row[col]

        # Skip the name col — already in the header
        if col == name_col:
            continue

        # osm_geometry: show summary text, not raw dict
        if col == "osm_geometry":
            display = _geometry_summary(val)
            rows_html.append(_table_row(col, display))
            continue

        # Skip NaN / None
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

        rows_html.append(_table_row(col, display))

    header = (
        f"<tr><th colspan='2' style='"
        f"background:#e8f0fe;padding:7px 10px;text-align:left;"
        f"font-size:13px;font-weight:600;border-bottom:1px solid #c5cae9'>"
        f"{plant_name}</th></tr>"
    )
    return (
        "<table style='font-family:sans-serif;font-size:12px;"
        "border-collapse:collapse;min-width:300px;max-width:440px'>"
        + header
        + "".join(rows_html)
        + "</table>"
    )


def _table_row(col: str, display: str) -> str:
    return (
        f"<tr style='border-bottom:1px solid #eeeeee'>"
        f"<td style='color:#666;padding:3px 8px;white-space:nowrap;vertical-align:top'>{col}</td>"
        f"<td style='padding:3px 8px;word-break:break-word'>{display}</td>"
        f"</tr>"
    )


# ---------------------------------------------------------------------------
# OSM geometry overlay
# ---------------------------------------------------------------------------


def _add_geometry_overlay(
    m: folium.Map,
    row: pd.Series,
    color: str,
    tooltip: str,
) -> None:
    """Draw an OSM polygon/polyline on the map when geometry data is present.

    Args:
        m: The folium map to add the overlay to.
        row: The DataFrame row containing an ``osm_geometry`` column.
        color: Stroke/fill colour for the GeoJSON shape.
        tooltip: Tooltip text shown on hover.
    """
    geom = row.get("osm_geometry")
    if geom is None or (isinstance(geom, float) and pd.isna(geom)):
        return
    if isinstance(geom, str):
        try:
            geom = json.loads(geom)
        except (json.JSONDecodeError, ValueError):
            return
    if not isinstance(geom, dict) or geom.get("type") not in ("Polygon", "LineString"):
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
    ).add_to(m)


# ---------------------------------------------------------------------------
# Unmatched-plants sidebar
# ---------------------------------------------------------------------------


def _build_unmatched_sidebar_html(
    dfs: list[pd.DataFrame],
    labels: list[str],
    name_col: str | None,
    fuel_col: str | None,
) -> str:
    """Return a self-contained HTML/CSS/JS string for the unmatched-plants sidebar.

    The sidebar is a fixed-position panel on the left edge of the map.  A toggle
    button (always visible) shows/hides the panel.  Inside, each label (country /
    dataset) is rendered as a ``<details>`` block whose ``<summary>`` shows the
    count; clicking it expands a bullet list of plant names.

    Args:
        dfs: The same DataFrames passed to ``build_map``.
        labels: Corresponding display labels.
        name_col: Column that holds the plant name.
        fuel_col: Column that holds the fuel type (shown in small italic text).

    Returns:
        str: HTML string to inject into the map, or ``""`` when nothing is unmatched.
    """
    sections: list[str] = []
    total_unmatched = 0

    for df, label in zip(dfs, labels):
        if "lat" not in df.columns or "lon" not in df.columns:
            unmatched = df
        else:
            unmatched = df[df["lat"].isna() | df["lon"].isna()].copy()

        if len(unmatched) == 0:
            continue

        total_unmatched += len(unmatched)

        items: list[str] = []
        for _, row in unmatched.iterrows():
            name = (
                str(row[name_col]) if name_col and name_col in row.index else "\u2014"
            )
            name = _html.escape(name)
            fuel_tag = ""
            if fuel_col and fuel_col in row.index:
                fval = row[fuel_col]
                if fval is not None and not (isinstance(fval, float) and pd.isna(fval)):
                    fuel_tag = f'<span class="rbc-fuel">{_html.escape(str(fval).strip())}</span>'
            items.append(f"<li>{name}{fuel_tag}</li>")

        sections.append(
            f'<details class="rbc-country">'
            f"<summary>{_html.escape(label)} "
            f'<span class="rbc-count">({len(unmatched)})</span></summary>'
            f"<ul>{''.join(items)}</ul>"
            f"</details>"
        )

    if not sections:
        return ""

    n_countries = len(sections)
    sections_html = "\n".join(sections)

    css = """\
<style>
  #rbc-sidebar {
    position: fixed;
    top: 60px;
    left: 10px;
    z-index: 9999;
    font-family: sans-serif;
    font-size: 13px;
    width: 260px;
  }
  #rbc-sidebar-toggle {
    background: #fff;
    border: 1px solid #aaa;
    border-radius: 4px 4px 0 0;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 13px;
    box-shadow: 0 1px 5px rgba(0,0,0,0.25);
    display: block;
    width: 100%;
    text-align: left;
    border-bottom: none;
  }
  #rbc-sidebar-panel {
    background: rgba(255,255,255,0.97);
    border: 1px solid #aaa;
    border-top: none;
    border-radius: 0 0 6px 6px;
    box-shadow: 0 3px 10px rgba(0,0,0,0.18);
    padding: 8px 10px 10px;
    max-height: 65vh;
    overflow-y: auto;
    display: none;
  }
  #rbc-sidebar-panel.rbc-open { display: block; }
  .rbc-panel-title {
    margin: 0 0 2px;
    font-size: 12px;
    font-weight: 700;
    color: #c0392b;
  }
  .rbc-panel-subtitle {
    color: #999;
    font-size: 11px;
    margin: 0 0 8px;
  }
  .rbc-country > summary {
    cursor: pointer;
    font-weight: 600;
    padding: 5px 2px;
    border-bottom: 1px solid #eee;
    list-style: none;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 12px;
  }
  .rbc-country > summary::-webkit-details-marker { display: none; }
  .rbc-country > summary::before {
    content: '\25B6';
    font-size: 8px;
    margin-right: 5px;
    transition: transform 0.15s;
    display: inline-block;
    flex-shrink: 0;
  }
  .rbc-country[open] > summary::before { transform: rotate(90deg); }
  .rbc-count { color: #bbb; font-weight: 400; font-size: 11px; margin-left: 4px; }
  .rbc-country ul {
    margin: 4px 0 6px 16px;
    padding: 0;
    list-style: disc;
  }
  .rbc-country li {
    padding: 1px 0;
    color: #444;
    line-height: 1.4;
    font-size: 11px;
  }
  .rbc-fuel {
    margin-left: 4px;
    font-size: 10px;
    color: #aaa;
    font-style: italic;
  }
</style>"""

    js = """\
<script>
  function rbcToggleSidebar() {
    document.getElementById('rbc-sidebar-panel').classList.toggle('rbc-open');
  }
</script>"""

    body = (
        f'<div id="rbc-sidebar">\n'
        f'  <button id="rbc-sidebar-toggle" onclick="rbcToggleSidebar()">'
        f"&#9888; Unmatched ({total_unmatched})</button>\n"
        f'  <div id="rbc-sidebar-panel">\n'
        f'    <p class="rbc-panel-title">Unmatched Power Plants</p>\n'
        f'    <p class="rbc-panel-subtitle">'
        f"{total_unmatched} plant(s) across {n_countries} country(s)</p>\n"
        f"{sections_html}\n"
        f"  </div>\n"
        f"</div>"
    )

    return f"{css}\n{js}\n{body}\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _build_legend_html(colors: dict[str, str], title: str = "Match source") -> str:
    """Return a self-contained HTML string for a small fixed-position map legend.

    Args:
        colors: Mapping of label → folium color name (e.g. ``{"ppm_direct": "green"}``).
        title: Legend heading text.

    Returns:
        str: HTML/CSS/JS to inject into the folium map.
    """
    # Folium color names map to CSS colors via a small lookup
    css_colors: dict[str, str] = {
        "red": "#d63031",
        "blue": "#0984e3",
        "green": "#27ae60",
        "purple": "#8e44ad",
        "orange": "#e67e22",
        "darkred": "#922b21",
        "lightred": "#f1948a",
        "beige": "#f5cba7",
        "darkblue": "#1a5276",
        "darkgreen": "#1e8449",
        "cadetblue": "#2e86c1",
        "darkpurple": "#6c3483",
        "white": "#ffffff",
        "pink": "#f48fb1",
        "lightblue": "#5dade2",
        "lightgreen": "#82e0aa",
        "gray": "#aaaaaa",
        "black": "#222222",
        "lightgray": "#cccccc",
    }

    rows = ""
    for label, folium_color in colors.items():
        css_color = css_colors.get(folium_color.lower(), folium_color)
        rows += (
            f"<div style='display:flex;align-items:center;margin-bottom:4px'>"
            f"<span style='display:inline-block;width:12px;height:12px;border-radius:50%;"
            f"background:{css_color};margin-right:7px;flex-shrink:0;border:1px solid rgba(0,0,0,0.2)'></span>"
            f"<span style='font-size:12px;color:#333'>{label}</span>"
            f"</div>"
        )

    return (
        "<div id='rbc-legend' style='"
        "position:fixed;bottom:30px;right:10px;z-index:9999;"
        "background:rgba(255,255,255,0.95);border:1px solid #bbb;"
        "border-radius:6px;padding:10px 14px;"
        "box-shadow:0 2px 8px rgba(0,0,0,0.18);font-family:sans-serif'>"
        f"<div style='font-weight:700;font-size:12px;margin-bottom:7px;"
        f"border-bottom:1px solid #eee;padding-bottom:5px'>{title}</div>"
        + rows
        + "</div>"
    )


def build_map(
    dfs: pd.DataFrame | list[pd.DataFrame],
    labels: list[str] | None = None,
    name_col: str | None = None,
    fuel_col: str | None = None,
    output_path: Path | str | None = None,
    open_browser: bool = True,
    cluster_markers: bool = True,
    tiles: str = "OpenStreetMap",
) -> folium.Map:
    """Build an interactive Leaflet map from one or more coordinate DataFrames.

    When the DataFrames contain a ``match_source`` column (produced by the ENTSOE
    enrichment pipeline) pin colours reflect the matching strategy used rather
    than the fuel type, and a legend is added to the bottom-right corner.
    Otherwise pins are coloured by fuel type as before.

    Each matched power plant is rendered as a clickable pin.  Clicking a pin
    opens a popup table that lists every column in
    the DataFrame — URL-like columns (``osm_url``, ``*_url``, …) become
    clickable hyperlinks.  When an ``osm_geometry`` polygon is present it is also
    drawn as a transparent overlay on the map.

    Multiple DataFrames are shown as separate toggleable layers via the built-in
    layer control (top-right corner).

    Args:
        dfs: A single ``pd.DataFrame`` or a list of DataFrames as returned by
            ``CoordinateLocator.run_pipeline()``.
        labels: Display name for each DataFrame shown in the layer control.
            Defaults to ``["Dataset 1", "Dataset 2", ...]``.
        name_col: Column holding the plant name used as the popup header and
            marker tooltip.  Auto-detected from column names when ``None``.
        fuel_col: Column holding the fuel/energy type used to colour markers.
            Auto-detected from column names when ``None``.
        output_path: File path for the saved HTML map.  Defaults to a temporary
            file in the system's temp directory.
        open_browser: Open the resulting HTML file in the default browser
            immediately after saving.  Defaults to ``True``.
        cluster_markers: Group nearby markers with ``MarkerCluster`` when zoomed
            out.  Defaults to ``True``.
        tiles: Tile provider name accepted by ``folium.Map`` (e.g.
            ``"OpenStreetMap"``, ``"CartoDB positron"``).
            Defaults to ``"OpenStreetMap"``.

    Returns:
        folium.Map: The constructed map object.  Useful for inline display in
        Jupyter notebooks (just return it as the last expression in a cell).

    Raises:
        ValueError: If ``dfs`` is empty or ``labels`` length mismatches ``dfs``.
    """
    if isinstance(dfs, pd.DataFrame):
        dfs = [dfs]
    if not dfs:
        raise ValueError("At least one DataFrame must be supplied.")
    if labels is None:
        labels = [f"Dataset {i + 1}" for i in range(len(dfs))]
    elif len(labels) != len(dfs):
        raise ValueError("`labels` must have the same length as `dfs`.")

    # --- auto-detect name / fuel / match_source columns from the first non-empty DataFrame
    match_source_col: str | None = None
    for df in dfs:
        if len(df) == 0:
            continue
        cols_lower = {c.lower(): c for c in df.columns}
        if name_col is None:
            for candidate in ("name", "plantname", "plant_name", "m_rid", "mrid"):
                if candidate in cols_lower:
                    name_col = cols_lower[candidate]
                    break
            if name_col is None:
                name_col = df.columns[0]
        if fuel_col is None:
            for candidate in (
                "fueltype",
                "fuel_type",
                "fuel",
                "psr_type",
                "psrtype",
                "pp.fuel_type",
            ):
                if candidate in cols_lower:
                    fuel_col = cols_lower[candidate]
                    break
        if match_source_col is None and "match_source" in cols_lower:
            match_source_col = cols_lower["match_source"]
        break

    use_match_source_colors = match_source_col is not None

    # --- gather all valid coordinates to compute map centre + bounds
    all_lats: list[float] = []
    all_lons: list[float] = []
    for df in dfs:
        matched = df.dropna(subset=["lat", "lon"])
        all_lats.extend(matched["lat"].astype(float).tolist())
        all_lons.extend(matched["lon"].astype(float).tolist())

    if not all_lats:
        logger.warning(
            "No matched coordinates found in any DataFrame — returning empty map."
        )
        return folium.Map(tiles=tiles, zoom_start=4)

    centre = [sum(all_lats) / len(all_lats), sum(all_lons) / len(all_lons)]
    m = folium.Map(location=centre, zoom_start=6, tiles=tiles)

    # --- markers: one global layer per match_source (ENTSOE) or one per dataset (legacy)
    n_colors = len(_DATASET_COLORS)

    if use_match_source_colors:
        # ENTSOE mode: first aggregate ALL datasets into per-match_source buckets,
        # then create ONE FeatureGroup per match_source.  A single checkbox in the
        # layer control therefore toggles that algorithm's pins across every zone.
        source_to_rows: dict[str, list[pd.Series]] = {}

        for df, label in zip(dfs, labels):
            matched = df.dropna(subset=["lat", "lon"])
            if len(matched) == 0:
                continue
            matched = matched.copy()
            if match_source_col and match_source_col in matched.columns:
                matched["_ms_key"] = (
                    matched[match_source_col].fillna("unmatched").astype(str)
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
            rows_for_source = source_to_rows[source_key]
            color = _match_source_color(source_key)

            fg = folium.FeatureGroup(name=source_key, show=True)
            mt: folium.FeatureGroup | folium.plugins.MarkerCluster
            if cluster_markers:
                mt = folium.plugins.MarkerCluster()
            else:
                mt = fg

            for row in rows_for_source:
                lat = float(row["lat"])
                lon = float(row["lon"])
                tooltip_text = (
                    str(row[name_col]) if name_col and name_col in row.index else ""
                )
                folium.Marker(
                    location=[lat, lon],
                    popup=folium.Popup(_popup_html(row, name_col), max_width=460),
                    tooltip=tooltip_text,
                    icon=folium.Icon(color=color, icon="bolt", prefix="fa"),
                ).add_to(mt)
                _add_geometry_overlay(m, row, color, tooltip_text)

            if cluster_markers:
                mt.add_to(fg)
            fg.add_to(m)
            total_added += len(rows_for_source)
            logger.info(
                f"Match-source layer '{source_key}': {len(rows_for_source)} marker(s)."
            )

        logger.info(
            f"Total: {total_added} markers across {len(source_to_rows)} "
            f"match-source layer(s)."
        )

    else:
        # Legacy mode: one FeatureGroup per dataset, coloured by fuel type
        for idx, (df, label) in enumerate(zip(dfs, labels)):
            matched = df.dropna(subset=["lat", "lon"])
            if len(matched) == 0:
                logger.info(f"'{label}': no matched rows — layer skipped.")
                continue

            fallback_color = _DATASET_COLORS[idx % n_colors]
            feature_group = folium.FeatureGroup(name=label, show=True)
            marker_target: folium.FeatureGroup | folium.plugins.MarkerCluster
            if cluster_markers:
                cluster = folium.plugins.MarkerCluster()
                marker_target = cluster
            else:
                marker_target = feature_group

            for _, row in matched.iterrows():
                lat = float(row["lat"])
                lon = float(row["lon"])
                fueltype = row.get(fuel_col) if fuel_col else None
                color = (
                    _fueltype_color(fueltype)
                    if fueltype is not None
                    and not (isinstance(fueltype, float) and pd.isna(fueltype))
                    else fallback_color
                )
                tooltip_text = (
                    str(row[name_col]) if name_col and name_col in row.index else ""
                )
                folium.Marker(
                    location=[lat, lon],
                    popup=folium.Popup(_popup_html(row, name_col), max_width=460),
                    tooltip=tooltip_text,
                    icon=folium.Icon(color=color, icon="bolt", prefix="fa"),
                ).add_to(marker_target)
                _add_geometry_overlay(m, row, color, tooltip_text)

            if cluster_markers:
                cluster.add_to(feature_group)
            feature_group.add_to(m)
            logger.info(
                f"'{label}': added {len(matched)} marker(s) "
                f"({len(df) - len(matched)} unmatched rows omitted)."
            )

    folium.LayerControl(collapsed=False).add_to(m)

    # --- inject match-source legend when applicable
    if use_match_source_colors:
        # Collect only the source values actually present in the data
        present_sources: dict[str, str] = {}
        for df in dfs:
            if match_source_col and match_source_col in df.columns:
                for val in df[match_source_col].dropna().unique():
                    key = str(val).strip().lower()
                    if key not in present_sources:
                        present_sources[key] = _MATCH_SOURCE_COLORS.get(
                            key, _MATCH_SOURCE_DEFAULT_COLOR
                        )
        if present_sources:
            legend_html = _build_legend_html(present_sources)
            m.get_root().html.add_child(folium.Element(legend_html))

    # --- inject unmatched-plants sidebar (auto-extracted from NaN lat/lon rows)
    sidebar_html = _build_unmatched_sidebar_html(dfs, labels, name_col, fuel_col)
    if sidebar_html:
        m.get_root().html.add_child(folium.Element(sidebar_html))

    m.fit_bounds(
        [[min(all_lats), min(all_lons)], [max(all_lats), max(all_lons)]],
        padding=(30, 30),
    )

    # --- save
    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, prefix="rbc_plants_"
        )
        output_path = Path(tmp.name)
        tmp.close()
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    m.save(str(output_path))
    logger.info(f"Map saved → {output_path}")

    if open_browser:
        webbrowser.open(output_path.as_uri())

    return m


# ---------------------------------------------------------------------------
# CLI / quick-test entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from pathlib import Path

    from rbc.coordinates.orchestrator import CoordinateLocator

    input_dir = Path("data/testdata/entsoe/1h/10YNL----------L")
    cl = CoordinateLocator(input_dir=input_dir, output_dir=Path("data/testdata/entsoe"))
    df = cl.run_pipeline()
    if df is not None and len(df) > 0:
        build_map(df, labels=["Netherlands (ENTSO-E)"])
