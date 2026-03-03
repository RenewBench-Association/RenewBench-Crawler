#!/usr/bin/env python
"""IESO DATA DOWNLOAD SCRIPT.

Download data from IESO website for Ontario, Canada.
"""

import argparse
from argparse import ArgumentParser

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.energy.ieso import IesoDownloader
from rbc.utils import setup_logging

SOURCE = "ieso"


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(prog="IESO data download")
    parser.add_argument(
        "-y",
        "--years",
        nargs="+",
        type=int,
        default=list(range(2010, 2026)),  # these are the available years for hourly gen
        help=f"Years to download. Example: -y 2020 2021. "
        f"Default: {list(range(2010, 2026))}",
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
        "Example: -o paths.dst_dir_raw=/your/path/",
    )
    return parser.parse_args()


def main() -> None:
    """Coordinating IESO data download."""
    args = parse_arguments()
    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None

    cfg = load_config(source=SOURCE, overrides=overrides)
    setup_logging(output_dir=cfg.paths.dst_dir_raw)
    logger.info(f"Flags for the '{SOURCE}' download:\n{args}")
    logger.info(f"Config for the '{SOURCE}' download:\n{cfg}")

    downloader = IesoDownloader(
        output_path=cfg.paths.dst_dir_raw,
        years=args.years,
        resume=args.resume,
    )
    downloader.download_data()


if __name__ == "__main__":
    main()
