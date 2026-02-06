#!/usr/bin/env python
"""EIA DATA DOWNLOAD SCRIPT.

Download data from EIA website for the USA.
"""

import argparse
from argparse import ArgumentParser

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.energy.eia import EiaDownloader

SOURCE = "eia"


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(prog="EIA data download")
    parser.add_argument(
        "-y",
        "--years",
        nargs="+",
        type=int,
        default=list(range(2019, 2026)),  # these are the available years for hourly gen
        help=f"Years to download. Example: -y 2020 2021. "
        f"Default: {list(range(2019, 2026))}",
    )
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
    """Coordinating EIA data download."""
    args = parse_arguments()
    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None

    cfg = load_config(source=SOURCE, overrides=overrides)
    logger.info(f"Config loaded for {SOURCE}:\n{cfg}")

    downloader = EiaDownloader(
        token=cfg.access.api_key,
        output_path=cfg.paths.dst_dir_raw,
        years=args.years,
        resume=True,
    )
    downloader.download_data()


if __name__ == "__main__":
    main()
