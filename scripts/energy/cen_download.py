#!/usr/bin/env python
"""CEN DATA DOWNLOAD SCRIPT.

Download data from CEN website for Chile.
"""

from argparse import ArgumentParser, Namespace
from datetime import datetime

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.energy.cen import CenDownloader
from rbc.energy.cen.downloader import MIN_YEAR
from rbc.utils import setup_logging

SOURCE = "cen"


def parse_arguments() -> Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(prog="CEN data download")
    parser.add_argument(
        "-y",
        "--years",
        nargs="+",
        type=int,
        default=list(range(MIN_YEAR, datetime.now().year + 1)),  # available years
        help=f"Years to download. Example: -y 2020 2021. "
        f"Default: {list(range(MIN_YEAR, datetime.now().year + 1))}",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Do not resume download from a previous checkpoint.",
    )
    parser.set_defaults(resume=True)
    parser.add_argument(
        "-o",
        "--cfg_options",
        action="append",
        help="Override YAML config values (supports nested keys). "
        "Example: -o paths.dst_dir_raw=/your/path/ -o "
        "access.api_key=YOUR-SECRET-KEY",
    )
    return parser.parse_args()


def main() -> None:
    """Coordinating CEN data download."""
    args = parse_arguments()
    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None

    cfg = load_config(source=SOURCE, overrides=overrides)
    setup_logging(output_dir=cfg.paths.dst_dir_raw)
    logger.info(f"Flags for the '{SOURCE}' download:\n{args}")
    logger.info(f"Config for the '{SOURCE}' download:\n{cfg}")

    downloader = CenDownloader(
        token=cfg.access.api_key,
        output_path=cfg.paths.dst_dir_raw,
        years=args.years,
        resume=args.resume,
    )
    downloader.download_data()


if __name__ == "__main__":
    main()
