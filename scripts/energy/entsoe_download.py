#!/usr/bin/env python
"""ENTSOE-E DATA DOWNLOAD SCRIPT.

Download data from ENTSO-E Transparency Platform for European bidding zones.
"""

import argparse
from argparse import ArgumentParser

from entsoe.utils import mappings
from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.energy.entsoe import EntsoeDownloader
from rbc.utils import setup_logging

SOURCE = "entsoe"


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(prog="Entso-E data download")
    parser.add_argument(
        "-y",
        "--years",
        nargs="+",
        type=int,
        default=list(range(2010, 2026)),
        help=f"Years to download. Example: -y 2020 2021. "
        f"Default: {list(range(2010, 2026))}",
    )
    parser.add_argument(
        "-bz",
        "--bidding_zones",
        nargs="+",
        type=str,
        choices=list(mappings.keys()),
        default=list(mappings.keys()),
        metavar="BIDDING_ZONES",
        help="Bidding zones to download. "
        "Example: -b '10YES-REE------0' '10YFR-RTE------C'. "
        "Default: All (see entsoe.utils.mappings)",
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
    """Coordinating Entso-E data download."""
    args = parse_arguments()
    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None

    cfg = load_config(source=SOURCE, overrides=overrides)
    setup_logging(output_dir=cfg.paths.dst_dir_raw)
    logger.info(f"Flags for the '{SOURCE}_download' run:\n{args}")
    logger.info(f"Config for the '{SOURCE}_download' run:\n{cfg}")

    downloader = EntsoeDownloader(
        token=cfg.access.api_key,
        output_path=cfg.paths.dst_dir_raw,
        bidding_zones=args.bidding_zones,
        years=args.years,
        resume=args.resume,
    )
    downloader.download_data()


if __name__ == "__main__":
    main()
