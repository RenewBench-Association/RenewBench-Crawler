#!/usr/bin/env python
"""ENTSOE-E DATA DOWNLOAD SCRIPT.

Download data from ENTSO-E Transparency Platform for European bidding zones.
"""

from argparse import ArgumentParser, Namespace
from datetime import datetime
from pprint import pformat

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.energy.entsoe import EntsoeDownloader
from rbc.energy.entsoe.mappings import ACTIVE_ZONES, MIN_YEAR
from rbc.utils import setup_logging

SOURCE = "entsoe"


def parse_arguments() -> Namespace:
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
        default=list(range(MIN_YEAR, datetime.now().year + 1)),
        help=f"Years to download. Example: -y 2020 2021. "
        f"Default: {list(range(MIN_YEAR, datetime.now().year + 1))}",
    )
    parser.add_argument(
        "-bz",
        "--bidding_zones",
        nargs="+",
        type=str,
        choices=ACTIVE_ZONES,
        default=ACTIVE_ZONES,
        metavar="BIDDING_ZONES",
        help="Bidding zone EIC codes to download. "
        "Example: -b '10YES-REE------0' '10YFR-RTE------C'. "
        "Default: All zones that had/have generation data per unit "
        "(see rbc.energy.entsoe.mappings.py)",
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
    logger.info(f"Flags for download:\n{pformat(vars(args), sort_dicts=False)}")
    logger.info(f"Config schema for download:\n{pformat(dict(cfg), sort_dicts=False)}")

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
