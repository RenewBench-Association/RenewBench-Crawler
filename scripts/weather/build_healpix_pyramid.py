#!/usr/bin/env python
"""HEALPIX PYRAMID REGRIDDING SCRIPT.

Regrid weather reanalysis sources onto a shared HEALPix pyramid and write
each (model_name, time_res, healpix_level) into its own Zarr store.
"""

import argparse
from argparse import ArgumentParser

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.utils import setup_logging
from rbc.weather.regridding.barra2 import Barra2Regridder
from rbc.weather.regridding.era5 import Era5Regridder
from rbc.weather.regridding.icon_dream import IconDreamRegridder
from rbc.weather.regridding.store import HealpixZarrWriter

SOURCE = "regrid_healpix"

REGRIDDER_CLASSES = {
    "era5": Era5Regridder,
    "barra2_r2": Barra2Regridder,
    "barra2_c2": Barra2Regridder,
    "barra2_c2_20min": Barra2Regridder,
    "icon_dream_global": IconDreamRegridder,
    "icon_dream_eu": IconDreamRegridder,
}

# Barra2Regridder/IconDreamRegridder each need a "model" kwarg the other
# regridders don't -- kept separate from REGRIDDER_CLASSES so the main loop's
# constructor call stays generic for every source.
_EXTRA_KWARGS: dict[str, dict] = {
    "barra2_r2": {"model": "R2"},
    "barra2_c2": {"model": "C2"},
    "barra2_c2_20min": {"model": "C2_20min"},
    "icon_dream_global": {"model": "global"},
    "icon_dream_eu": {"model": "eu"},
}

# Maps each source_name to its contract "model_name" for the regridded output
# store. barra2_c2 and barra2_c2_20min deliberately share one ("barra2_c2")
# -- they're the same physical model/grid, sampled at two temporal
# resolutions, distinguished by the "1h"/"20min" subdirectory instead.
_MODEL_NAME: dict[str, str] = {
    "era5": "era5",
    "barra2_r2": "barra2_r2",
    "barra2_c2": "barra2_c2",
    "barra2_c2_20min": "barra2_c2",
    "icon_dream_global": "icon_dream_global",
    "icon_dream_eu": "icon_dream_eu",
}

# Each source's temporal resolution, per the weather Zarr contract's
# "{model_name}/{time_res}/level_{N}.zarr" output layout.
_TIME_RES: dict[str, str] = {
    "era5": "1h",
    "barra2_r2": "1h",
    "barra2_c2": "1h",
    "barra2_c2_20min": "20min",
    "icon_dream_global": "1h",
    "icon_dream_eu": "1h",
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
        help=f"Sources to regrid. Choices: {list(REGRIDDER_CLASSES)}.",
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
        help="Canonical variable names to regrid. Default: every variable "
        "present in the raw files.",
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
    setup_logging(output_dir=cfg.dst_data_base_dir)
    logger.info(f"Flags for the '{SOURCE}' regrid:\n{args}")
    logger.info(f"Config for the '{SOURCE}' regrid:\n{cfg}")

    min_level = args.healpix_min_level or cfg.healpix_min_level
    max_level_overrides = _parse_max_level_overrides(args.healpix_max_level)

    writer = HealpixZarrWriter(base_dir=cfg.dst_data_base_dir, min_level=min_level)

    for name in args.sources:
        model_name = _MODEL_NAME[name]
        time_res = _TIME_RES[name]
        regridder = REGRIDDER_CLASSES[name](
            raw_dir=cfg.raw_data_base_dir,
            source_name=name,
            weights_cache_dir=writer.weights_cache_dir(model_name),
            checkpoint_path=writer.checkpoint_path(model_name, time_res),
            min_level=min_level,
            max_level=max_level_overrides.get(name, cfg.healpix_max_level[name]),
            variables=args.variables or (cfg.variables or {}).get(name) or [],
            years=args.years,
            months=args.months,
            dry_run=args.dry_run,
            resume=args.resume,
            **_EXTRA_KWARGS.get(name, {}),
        )

        for task, pyramid in regridder.regrid():
            writer.append(
                model_name=model_name, time_res=time_res, task=task, pyramid=pyramid
            )
            # Only mark done once the write above actually succeeds -- see
            # GridRegridder.mark_done()'s docstring for why this can't
            # happen inside regrid() itself.
            regridder.mark_done(task)
            writer.emit_stac_item(
                model_name=model_name, time_res=time_res, task=task, pyramid=pyramid
            )


if __name__ == "__main__":
    main()
