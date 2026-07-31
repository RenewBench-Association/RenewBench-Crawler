"""Static HTML/CSS/JS templates for the folium map built in rbc.coordinates.map.

Keeping these as plain string templates here keeps map.py focused on data logic
(which rows go where, which color to use) rather than markup.
"""

# Folium's named marker colors have no hex table -> this is used to render in the HTML legend
FOLIUM_TO_HEX: dict[str, str] = {
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

# ---------------------------------------------------------------------------
# Marker popup table
# ---------------------------------------------------------------------------
_POPUP_HEADER = (
    "<tr><th colspan='2' style='"
    "background:#e8f0fe;padding:7px 10px;text-align:left;"
    "font-size:13px;font-weight:600;border-bottom:1px solid #c5cae9'>"
    "{plant_name}</th></tr>"
)

_POPUP_ROW = (
    "<tr style='border-bottom:1px solid #eeeeee'>"
    "<td style='color:#666;padding:3px 8px;white-space:nowrap;vertical-align:top'>{col}</td>"
    "<td style='padding:3px 8px;word-break:break-word'>{display}</td>"
    "</tr>"
)

_POPUP_TABLE = (
    "<table style='font-family:sans-serif;font-size:12px;"
    "border-collapse:collapse;min-width:300px;max-width:440px'>{header}{rows}</table>"
)


def popup_row_html(col: str, display: str) -> str:
    """Render a single label/value row for a marker popup table."""
    return _POPUP_ROW.format(col=col, display=display)


def popup_table_html(plant_name: str, rows_html: str) -> str:
    """Render the full popup table for one marker.

    Args:
        plant_name: Plant name shown in the header row.
        rows_html: Concatenated ``popup_row_html`` output for every other column.

    Returns:
        str: Self-contained HTML string for use in a ``folium.Popup``.
    """
    return _POPUP_TABLE.format(
        header=_POPUP_HEADER.format(plant_name=plant_name), rows=rows_html
    )


# ---------------------------------------------------------------------------
# Legend
# ---------------------------------------------------------------------------
_LEGEND_ROW = (
    "<div style='display:flex;align-items:center;margin-bottom:4px'>"
    "<span style='display:inline-block;width:12px;height:12px;border-radius:50%;"
    "background:{css_color};margin-right:7px;flex-shrink:0;border:1px solid rgba(0,0,0,0.2)'></span>"
    "<span style='font-size:12px;color:#333'>{label}</span>"
    "</div>"
)

_LEGEND_PANEL = (
    "<div id='rbc-legend' style='"
    "position:fixed;bottom:30px;right:10px;z-index:9999;"
    "background:rgba(255,255,255,0.95);border:1px solid #bbb;"
    "border-radius:6px;padding:10px 14px;"
    "box-shadow:0 2px 8px rgba(0,0,0,0.18);font-family:sans-serif'>"
    "<div style='font-weight:700;font-size:12px;margin-bottom:7px;"
    "border-bottom:1px solid #eee;padding-bottom:5px'>{title}</div>{rows}</div>"
)


def legend_html(colors: dict[str, str], title: str = "Marker color legend") -> str:
    """Render the fixed-position map legend from a label -> folium-color mapping.

    Args:
        colors: Mapping of label -> folium color name (e.g. ``{"ppm_direct": "green"}``).
        title: Legend heading text.

    Returns:
        str: HTML/CSS to inject into the folium map.
    """
    rows_html = "".join(
        _LEGEND_ROW.format(
            css_color=FOLIUM_TO_HEX.get(color.lower(), color), label=label
        )
        for label, color in colors.items()
    )
    return _LEGEND_PANEL.format(title=title, rows=rows_html)


# ---------------------------------------------------------------------------
# Unmatched-plants sidebar
# ---------------------------------------------------------------------------
SIDEBAR_CSS = """\
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
    content: '\\25B6';
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

SIDEBAR_JS = """\
<script>
  function rbcToggleSidebar() {
    document.getElementById('rbc-sidebar-panel').classList.toggle('rbc-open');
  }
</script>"""

_SIDEBAR_ITEM = "<li>{name}{fuel_tag}</li>"
_SIDEBAR_FUEL_TAG = '<span class="rbc-fuel">{fuel}</span>'

_SIDEBAR_SECTION = (
    '<details class="rbc-country">'
    '<summary>{label} <span class="rbc-count">({count})</span></summary>'
    "<ul>{items}</ul>"
    "</details>"
)

_SIDEBAR_BODY = (
    '<div id="rbc-sidebar">\n'
    '  <button id="rbc-sidebar-toggle" onclick="rbcToggleSidebar()">'
    "&#9888; Unmatched ({total})</button>\n"
    '  <div id="rbc-sidebar-panel">\n'
    '    <p class="rbc-panel-title">Unmatched Power Plants</p>\n'
    '    <p class="rbc-panel-subtitle">{total} plant(s) across {n_countries} country(s)</p>\n'
    "{sections}\n"
    "  </div>\n"
    "</div>"
)


def sidebar_item_html(name: str, fuel: str | None) -> str:
    """Render one '<li>' item entry (EGE name + optional fuel tag) in the sidebar.

    Args:
        name (str): EGE name for '<li>' entry.
        fuel (str, optional): EGE fuel tag for '<li>' entry.

    Returns:
        str: HTML string for '<li>' entry.
    """
    fuel_tag = _SIDEBAR_FUEL_TAG.format(fuel=fuel) if fuel else ""
    return _SIDEBAR_ITEM.format(name=name, fuel_tag=fuel_tag)


def sidebar_section_html(label: str, count: int, items_html: str) -> str:
    """Render one collapsible '<details>' section (one per dataset/country) in the sidebar.

    Args:
        label (str): Name of '<details>' entry.
        count (int): Number of '<details>' entries.
        items_html: Concatenated ``sidebar_item_html`` output.
    """
    return _SIDEBAR_SECTION.format(label=label, count=count, items=items_html)


def sidebar_html(total_unmatched: int, n_countries: int, sections_html: str) -> str:
    """Render the full self-contained sidebar (CSS + JS + body).

    Args:
        total_unmatched: Total number of unmatched plants across all sections.
        n_countries: Number of sections (countries/datasets) with unmatched plants.
        sections_html: Concatenated ``sidebar_section_html`` output.

    Returns:
        str: HTML/CSS/JS string to inject into the folium map.
    """
    body = _SIDEBAR_BODY.format(
        total=total_unmatched, n_countries=n_countries, sections=sections_html
    )
    return f"{SIDEBAR_CSS}\n{SIDEBAR_JS}\n{body}\n"
