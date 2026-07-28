"""Coordinate/location finding orchestration.

Orchestrates coordinate finding for power-generation units via a declarative,
per-operator pipeline (see rbc.coordinates.pipelines):
- ENTSO-E uses its own EIC-code-driven pipeline (EntsoePipeline),
- every other operator uses the "default" pipeline (DefaultPipeline).
This setup may be enhanced in the future depending on the operator-specific needs.
"""

from pathlib import Path

import pandas as pd
from loguru import logger

from rbc.coordinates.map import build_map
from rbc.coordinates.mappings import OPERATOR_METADATA
from rbc.coordinates.pipelines import build_shared_locators, make_pipeline
from rbc.energy.utils import DownloadTask

DATE_PATTERN = DownloadTask._DATE_PATTERN  # pattern for relevant file names
TRES_PATTERN = DownloadTask._TRES_PATTERN  # pattern for one of the parent folders


def perform_coordinate_finding(
    source: str,
    input_dirs: list[Path | str],
    output_dir: Path | None = None,
    gem_dir: Path | None = None,
    update: bool = False,
    live: bool = False,
) -> None:
    """Main entry point for coordinating location finding.

    Args:
        source (str): Name of the energy source, e.g. "aemo".
        input_dirs (list[Path | str]): Paths of the directories containing input (".csv")
            files (somewhere).
        output_dir (Path | None): Path of the output directory. Defaults to None.
        gem_dir (Path | None): Path of the directory containing GEM files. Defaults to None.
        update (bool, optional): Whether to re-fetch OSM power plant data from the OSM
            (Overpass Turbo) API. Defaults to False.
        live (bool, optional): Whether to query the OSM (Overpass Turbo) API on every run.
            Defaults to False.
    """
    if source not in OPERATOR_METADATA:
        raise ValueError(f"Unknown energy source: '{source}'")

    csv_parent_dirs: list[Path] = _collect_dirs(input_dirs)
    csv_parent_dirs = [d for d in csv_parent_dirs if source in d.parts]

    # Build the expensive (network/CSV/parquet-backed) helper-data locators ONCE and share!
    shared = build_shared_locators(
        source=source, gem_dir=gem_dir, output_dir=output_dir
    )

    dataframes: list[pd.DataFrame] = []
    countries: list[str] = []
    sysop_name_cols: list[str] = []

    for csv_parent_dir in csv_parent_dirs:
        try:
            cl = make_pipeline(
                input_dir=csv_parent_dir,
                output_dir=output_dir,
                gem_loc=shared.gem_loc,
                ppdb_loc=shared.ppdb_loc,
                eic_reg=shared.eic_reg,
                osm_update=update,
                osm_live=live,
            )
            df = cl.run_pipeline()

            # Use explicit check to avoid pandas NA boolean ambiguity
            if df is not None and len(df) > 0:
                dataframes.append(df)
                countries.append(cl.country)
                sysop_name_cols.append(cl.sysop_name_col)
                logger.info(
                    f"{csv_parent_dir}: {df['lat'].notna().sum()}/{len(df)} matched."
                )

        except Exception as e:
            logger.warning(f"{csv_parent_dir}: skipped — {e}")

    if dataframes:
        # build_map works best with a name column; for ENTSOE the name col is prefixed
        map_dfs = []
        for idx, df_map in enumerate(dataframes):
            sysop_name_col = sysop_name_cols[idx]
            if sysop_name_col in df_map.columns and "Name" not in df_map.columns:
                df_map = df_map.copy()
                df_map["Name"] = df_map[sysop_name_col]
            map_dfs.append(df_map)

        build_map(map_dfs, labels=countries)
    else:
        logger.warning("No results found for the given input paths.")


def _collect_dirs(input_paths: list[Path | str]) -> list[Path]:
    """Resolve one or more input paths into a flat, sorted list of directories.

    The input list can contain:

    - A single folder — a directory that directly contains the CSV files (no subdirectories).
        Treated as one dir.
    - A container folder — a directory whose children contain the CSV files (somewhere).
        All subdirectories are searched and those collected that contain relevant CSVs.
    - Any mix of the two shapes above — each element is resolved independently and the
        results are concatenated.

    Args:
        input_paths (list): A list of paths of interest.

    Returns:
        list[Path]: Deduplicated, sorted list of resolved directories.
    """
    candidates = [Path(p) for p in input_paths]
    directories: set[Path] = set()

    for path in candidates:
        if not path.is_dir():
            logger.warning(f"'{path}' is not a directory — skipping!")
            continue

        for p in path.rglob("*.csv"):
            if DATE_PATTERN.match(p.stem) and any(
                TRES_PATTERN.match(prt) for prt in p.parts
            ):
                directories.add(p.parent.resolve())

    return sorted(directories)
