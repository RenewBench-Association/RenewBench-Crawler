#!/usr/bin/env python
"""OSM COUNTRY RELATION ID UPDATE SCRIPT."""

import ast
import inspect
import subprocess
import sys
from pathlib import Path
from pprint import pformat

import country_converter as coco
from loguru import logger

import rbc.coordinates.mappings as mappings
from rbc.coordinates.locators.osm_api import OVERPASS_SERVER_TIMEOUT, post_overpass
from rbc.energy.entsoe.mappings import ACTIVE_ZONES_METADATA

VAR_NAME = "COUNTRY_OSM_RELATION_ID_MAP"
existing_map: dict = getattr(mappings, VAR_NAME)


def main() -> None:
    """Updating OSM country relation IDs."""
    logger.info("Getting current OSM relation IDs for relevant operator countries...")

    # 1. Get map of all countries (alpha2 codes) to their OSM relation IDs
    new_map_all = _fetch_osm_country_relation_ids()
    if len(new_map_all) == 0:
        logger.error(
            "OSM relation IDs query failed (probably due to API overload). Try again later..."
        )
        return
    logger.info(
        f"All {len(new_map_all)} current OSM relation IDs loaded into mapping dict."
    )

    # 2. Get a list of relevant countries with which to filter & define the new, updated map
    relevant_codes = []
    for op, op_info in mappings.OPERATOR_METADATA.items():
        country = op_info["country"]
        if country == "Europe":
            eu_alpha2 = [i["alpha2"] for i in ACTIVE_ZONES_METADATA.values()]
            relevant_codes += eu_alpha2
        else:
            relevant_codes.append(coco.convert(names=country, to="ISO2"))

    new_map = dict(
        sorted({k: v for k, v in new_map_all.items() if k in relevant_codes}.items())
    )
    logger.info(f"Filtered mapping to get only the {len(new_map)} relevant countries.")

    # 3. Compare new to old mapping
    added = new_map.keys() - existing_map.keys()
    removed = existing_map.keys() - new_map.keys()
    changed = {
        k: (existing_map[k], new_map[k])
        for k in existing_map.keys() & new_map.keys()
        if existing_map[k] != new_map[k]
    }

    logger.info(
        f"Overview of OSM relation ID update:"
        f"\n- Added:\t{added},\n- Removed:\t{removed},\n- Changed:\t{changed}"
    )
    if removed and len(new_map) == 0:
        logger.error(f"Stopping {VAR_NAME} update: New map is empty!")
        return

    if added or removed or changed:
        # 4. If the mapping (keys and/or values) has changed, update the mappings' VAR_NAME!
        logger.info(f"Updating {VAR_NAME} in `mappings.py` file...")
        _update_mappings_file(new_map)
    else:
        logger.info("No changes made, no update required!")


# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------
def _fetch_osm_country_relation_ids() -> dict[str, int]:
    """Resolve every country's ISO 3166-1 alpha-2 code to its OSM relation ID.

    Returns:
        dict[str, int]: Mapping of alpha-2 code to OSM relation ID.
    """
    query = f"""
    [out:json][timeout:{OVERPASS_SERVER_TIMEOUT}];
    relation["type"="boundary"]["boundary"="administrative"]["admin_level"="2"]["ISO3166-1"];
    out tags;
    """
    data = post_overpass(query, "country-relation-ids")
    if data is None:
        return {}

    mapping: dict[str, int] = {}
    seen: dict[str, list[int]] = {}
    for el in data.get("elements", []):
        code = el.get("tags", {}).get("ISO3166-1")
        rel_id = el.get("id")
        if not isinstance(code, str) or not isinstance(rel_id, int):
            continue
        seen.setdefault(code.upper(), []).append(rel_id)

    for code, ids in seen.items():
        if len(ids) > 1:
            logger.warning(
                f"Multiple admin_level=2 relations carry ISO3166-1={code}: {ids}"
            )
        mapping[code] = ids[0]

    return dict(sorted(mapping.items()))


def _update_mappings_file(new_map: dict[str, int]) -> None:
    """Rewrite a module-level dict assignment in mappings.py with a new value.

    Locates the assignment of VAR_NAME in mappings.py via ast, replaces only VAR_NAME's
    content lines, ensures the result compiles, then writes and auto-formats.

    Args:
        new_map: The new dict value to assign.
    """
    # 1. Find current VAR_NAME definition in mappings.py file
    mapping_file = Path(inspect.getfile(mappings))
    content = mapping_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(mapping_file))

    target: ast.AnnAssign | None = None  # VAR_NAME is assumed to have typesetting
    for node in ast.iter_child_nodes(tree):  # check top-level only as global var
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == VAR_NAME
        ):
            target = node
            break

    if target is None:
        raise ValueError(f"Could not find '{VAR_NAME}' definition in {mapping_file}!")

    # 2. Define file content by inserting new VAR_NAME definition at right place
    lines = content.splitlines(keepends=True)
    start, end = target.lineno - 1, target.end_lineno  # right place (0-indexed start)

    new_text = (
        f"{VAR_NAME}: {ast.unparse(target.annotation)} = "  # with original typesetting
        f"{pformat(new_map, indent=4, sort_dicts=True)}\n"
    )
    new_lines = lines[:start] + [new_text] + lines[end:]
    updated_content = "".join(new_lines)

    # 3. Check compilation (error if it fails), write to file and run auto-formatter!
    compile(updated_content, str(mapping_file), "exec")
    mapping_file.write_text(updated_content, encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "ruff", "format", str(mapping_file)], check=True
    )

    logger.info(f"Successfully updated '{VAR_NAME}' in {mapping_file}.")


if __name__ == "__main__":
    main()
