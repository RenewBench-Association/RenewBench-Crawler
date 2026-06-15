#!/usr/bin/env python
"""EPIAS DATA DOWNLOAD SCRIPT.

Download data from EPIAS Transparency Platform for Turkey.
"""

from argparse import ArgumentParser, Namespace
from datetime import datetime
from pprint import pformat

from loguru import logger

from rbc.config.loader import load_config, parse_key_value_pairs
from rbc.energy.epias import EpiasDownloader
from rbc.energy.epias.downloader import MIN_YEAR
from rbc.utils import setup_logging

SOURCE = "epias"


def parse_arguments() -> Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(prog="EPIAS data download")
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
        "access.username=YOUR-SECRET-USERNAME",
    )
    return parser.parse_args()


def main() -> None:
    """Coordinating EPIAS data download."""
    args = parse_arguments()
    overrides = parse_key_value_pairs(args.cfg_options) if args.cfg_options else None

    cfg = load_config(source=SOURCE, overrides=overrides)
    setup_logging(output_dir=cfg.paths.dst_dir_raw)
    logger.info(f"Flags for download:\n{pformat(vars(args), sort_dicts=False)}")
    logger.info(f"Config schema download:\n{pformat(dict(cfg), sort_dicts=False)}")

    downloader = EpiasDownloader(
        username=cfg.access.username,
        password=cfg.access.password,
        output_path=cfg.paths.dst_dir_raw,
        years=args.years,
        resume=args.resume,
    )
    downloader.download_data()


if __name__ == "__main__":
    main()
