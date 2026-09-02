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

    csv_dirs: list[Path] = _collect_dirs(input_dirs)
    csv_dirs = [d for d in csv_dirs if source in d.parts]

    # Build the expensive (network/CSV/parquet-backed) helper-data locators ONCE and share!
    shared = build_shared_locators(
        source=source, gem_dir=gem_dir, output_dir=output_dir
    )
    logger.info(
        f"Initialized shared locators. Now analyzing {len(csv_dirs)} directories...\n--"
        "-------------------------------------------------------------------------------"
    )

    dataframes: list[pd.DataFrame] = []
    labels: list[str] = []

    name_col: str | None = None
    fuel_col: str | None = None

    for csv_dir in csv_dirs:
        try:
            cl = make_pipeline(
                input_dir=csv_dir,
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

                # define label by csv_path parts ("<source>_<tres>" or "<source>_<tres>_<bz>")
                label = "_".join(csv_dir.parts[csv_dir.parts.index(source) :])
                labels.append(label)

                name_col = cl.sysop_name_col if name_col is None else name_col
                fuel_col = cl.sysop_fuel_col if fuel_col is None else fuel_col

        except Exception as e:
            logger.exception(
                f"Error occurred while analysing {csv_dir}: {e}. Skipping..."
            )

    if dataframes:
        build_map(
            dataframes,
            labels=labels,
            name_col=name_col,
            fuel_col=fuel_col,
            output_dir=output_dir,
        )
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
