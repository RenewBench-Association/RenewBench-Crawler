#!/usr/bin/env python
"""HEALPIX PYRAMID REGRIDDING SCRIPT.

Regrid weather reanalysis sources onto a shared HEALPix pyramid and write
them into one combined Zarr store.
"""

import argparse
from argparse import ArgumentParser

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.utils import setup_logging
from rbc.weather.regridding.era5 import Era5Regridder
from rbc.weather.regridding.store import HealpixZarrWriter

SOURCE = "regrid_healpix"

# Only sources with an implemented regridder can be processed. Extend as
# Barra2Regridder/IconDreamRegridder land.
REGRIDDER_CLASSES = {
    "era5": Era5Regridder,
}


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Parsed command line arguments.
    """
    parser = ArgumentParser(prog="HEALPix pyramid regridding")

    parser.add_argument(
        "--sources",
        nargs="+",
        type=str,
        choices=list(REGRIDDER_CLASSES),
        default=list(REGRIDDER_CLASSES),
        help=f"Sources to regrid. Currently implemented: {list(REGRIDDER_CLASSES)}. "
        "BARRA2/ICON-DREAM regridders are not implemented yet.",
    )
    parser.add_argument(
        "-y",
        "--years",
        nargs="+",
        type=int,
        required=True,
        help="Years to regrid. Example: -y 2020 2021.",
    )
    parser.add_argument(
        "-m",
        "--months",
        nargs="+",
        type=str,
        choices=[f"{i:02d}" for i in range(1, 13)],
        default=None,
        metavar="MONTHS",
        help="Months to regrid (01-12). Example: -m 01 02 03. Default: all months.",
    )
    parser.add_argument(
        "-v",
        "--variables",
        nargs="+",
        type=str,
        default=None,
        metavar="VARIABLES",
        help="Canonical variable names to regrid. NOTE: not yet enforced -- "
        "every variable present in the raw files is currently processed "
        "regardless of this flag.",
    )
    parser.add_argument(
        "--healpix-min-level",
        type=int,
        default=None,
        help="Override the shared min_level from the config.",
    )
    parser.add_argument(
        "--healpix-max-level",
        action="append",
        metavar="SOURCE=LEVEL",
        help="Override one source's max_level from the config. "
        "Example: --healpix-max-level era5=7. Repeatable.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve tasks/weights without writing to the store.",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Do not resume from a previous checkpoint.",
    )
    parser.set_defaults(resume=True)

    parser.add_argument(
        "-o",
        "--cfg_options",
        action="append",
        help="Override YAML config values (supports nested keys). "
        "Example: -o healpix_min_level=5",
    )
    return parser.parse_args()


def _parse_max_level_overrides(pairs: list[str] | None) -> dict[str, int]:
    """Parse repeatable SOURCE=LEVEL overrides into a dict.

    Args:
        pairs (list[str] | None): Raw "source=level" strings from the CLI.

    Returns:
        dict[str, int]: Mapping of source name to overridden max_level.

    Raises:
        ArgumentTypeError: If a pair isn't in "source=level" format.
    """
    overrides: dict[str, int] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise argparse.ArgumentTypeError(
                f"Invalid format '{pair}', expected source=level"
            )
        source, level = pair.split("=", 1)
        overrides[source] = int(level)
    return overrides


def main() -> None:
    """Coordinate HEALPix regridding across configured sources."""
    args = parse_arguments()

    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None
    cfg = load_config(source=SOURCE, overrides=overrides)
    setup_logging(output_dir=cfg.paths.dst_zarr_store.parent)
    logger.info(f"Flags for the '{SOURCE}' regrid:\n{args}")
    logger.info(f"Config for the '{SOURCE}' regrid:\n{cfg}")

    min_level = args.healpix_min_level or cfg.healpix_min_level
    max_level_overrides = _parse_max_level_overrides(args.healpix_max_level)

    writer = HealpixZarrWriter(store_path=cfg.paths.dst_zarr_store, min_level=min_level)

    for name in args.sources:
        regridder = REGRIDDER_CLASSES[name](
            raw_dir=getattr(cfg.paths, f"{name}_raw_dir"),
            source_name=name,
            weights_cache_dir=cfg.paths.weights_cache_dir,
            min_level=min_level,
            max_level=max_level_overrides.get(name, cfg.healpix_max_level[name]),
            variables=args.variables or (cfg.variables or {}).get(name) or [],
            years=args.years,
            months=args.months,
            dry_run=args.dry_run,
            resume=args.resume,
        )

        for task, pyramid in regridder.regrid():
            writer.append(source_name=name, task=task, pyramid=pyramid)
            # Only mark done once the write above actually succeeds -- see
            # GridRegridder.mark_done()'s docstring for why this can't
            # happen inside regrid() itself.
            regridder.mark_done(task)
            writer.emit_stac_item(source_name=name, task=task, pyramid=pyramid)


if __name__ == "__main__":
    main()
