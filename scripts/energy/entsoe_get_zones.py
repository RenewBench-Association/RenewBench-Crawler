"""Probe ENTSO-E bidding zones for likely data availability.

This script performs a lightweight scan across ENTSO-E bidding zones by querying
only a small set of sample dates rather than every day of every year.

Features:
- incremental saving after every checked zone
- resume support
- Loguru logging to console and file

Usage:
    python scripts/entsoe_get_zones.py --token YOUR_TOKEN --output-dir outputs/entsoe_probe
    python scripts/entsoe_get_zones.py --token YOUR_TOKEN --output-dir outputs/entsoe_probe --resume
"""

from __future__ import annotations

import json
from argparse import ArgumentParser, Namespace
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from entsoe.config import set_config
from entsoe.Generation import ActualGenerationPerGenerationUnit
from entsoe.query.decorators import ServiceUnavailableError
from entsoe.utils import mappings
from loguru import logger

from rbc.utils import setup_logging


class EntsoeBZCollector:
    """Collect active bidding zone data.

    Attributes:
        dates (list[str]): List of dates to check.
        dates_per_year (int): Number of dates per year.
        results_by_zone (dict[str, Any]): Dictionary of result statistics per bidding zone.
        results_path (Path): Path of results JSON file.
        resume (bool): Whether to resume from previous data collection or not.
        years (list[str]): List of years to check.
    """

    def __init__(
        self,
        token: str,
        output_dir: Path,
        years: list,
        dates_per_year: int,
        resume: bool,
    ) -> None:
        """Initialize EntsoeBZCollector.

        Args:
            token (str): ENTSO-E bidding token.
            output_dir (Path): Output directory.
            years (list[str]): Years to collect.
            dates_per_year (int): Number of dates per year.
            resume (bool): Whether to resume from previous data collection or not.
        """
        self.results_path = Path(output_dir, "active_zones.json")
        self.resume = resume
        self.years = years
        self.dates_per_year = dates_per_year
        self.dates = self.build_sample_dates()

        if token is not None:
            set_config(security_token=token)

        logger.info(f"Saving to file: {self.results_path}")
        logger.info(f"Years: {self.years}")
        logger.info(f"Dates per year: {self.dates_per_year}")
        logger.info(
            f"Checking {len(mappings)} zones: {len(self.years)} years × "
            f"{self.dates_per_year} dates/year = {len(self.dates)} total checks"
        )
        logger.info(f"Resume mode: {self.resume}")

        if self.resume:
            self.results_by_zone = self._load_results()
            logger.info(f"Loaded {len(self.results_by_zone)} previously checked zones.")
        else:
            self.results_by_zone = {}
            logger.info("Starting from scratch.")

    def build_sample_dates(self) -> list[str]:
        """Build a list of sample dates (MM-DD) to probe.

        Returns:
            list[str]: List of all sample dates (YYYY-MM-DD).

        Raises:
            ValueError: If dates_per_year is invalid.
        """
        if self.dates_per_year == 1:
            mm_dd = ["12-15"]  # ensures inclusion even if recording started at year end
        elif self.dates_per_year == 2:
            mm_dd = ["03-15", "09-15"]
        elif self.dates_per_year == 3:
            mm_dd = ["01-15", "06-15", "12-15"]
        else:
            raise ValueError("dates_per_year must be one of: 1, 2, 3")

        return [f"{y}-{d}" for y in self.years for d in mm_dd]

    # ------------------------------------------------------------------
    # Main entrypoint for running / getting the mapping dict
    # ------------------------------------------------------------------
    def run(self):
        """Run the collection of bidding zones."""
        zones = list(mappings.keys())

        for i, zone in enumerate(zones, start=1):
            if self.resume and zone in self.results_by_zone:
                logger.info(f"[{i:>3}/{len(zones)}] Skipping {zone} - already checked.")
                continue

            logger.info(
                f"[{i:>3}/{len(zones)}] Checking {zone} ({mappings[zone]['name']})"
            )
            result = self._check_zone(zone=zone)
            self.results_by_zone[zone] = result
            self._save_results()

            logger.info(
                f"Completed checking {zone}:\t has_data={result['has_any_data']} | "
                f"hits={result['n_hits']} | first_year={result['first_year']} | "
                f"last_year={result['last_year']} | errors={result['errors']}"
            )

        self._print_summary()

    def _check_zone(self, zone: str) -> dict[str, Any]:
        """Check data availability for one zone.

        Args:
            zone (str): Zone to check.

        Returns:
            dict[str, Any]: Dictionary containing current bidding zone statistics.
        """
        hit_dates: list[str] = []
        miss_dates: list[str] = []
        error_counts: dict[str, int] = {}

        for date in self.dates:
            has_data, status = self._query_data(zone=zone, date=date)

            if has_data:
                hit_dates.append(date)
            elif has_data is False:
                miss_dates.append(date)
            else:
                error_counts[status] = error_counts.get(status, 0) + 1

        return {
            "zone": zone,
            "zone_name": mappings.get(zone, {}),
            "has_any_data": bool(hit_dates),
            "hit_dates": hit_dates,
            "n_hits": len(hit_dates),
            "n_misses": len(miss_dates),
            "errors": error_counts,
            **self._get_hit_stats(hit_dates),
        }

    @staticmethod
    def _query_data(zone: str, date: str) -> tuple[bool | None, str]:
        """Check whether a single zone/date query returns 'generation per unit' data.

        Args:
            zone (str): Zone to check.
            date (str): Date to check.

        Returns:
            tuple(bool | None, str): If error, None & status reason. If successful,
                bool for whether data was present.
        """
        dt = pd.Period(date, freq="D")

        try:
            result = ActualGenerationPerGenerationUnit(
                period_start=int(dt.strftime("%Y%m%d0000")),
                period_end=int(dt.strftime("%Y%m%d2359")),
                in_domain=zone,
                psr_type=None,
                registered_resource=None,
            ).query_api()

        except ServiceUnavailableError:
            return None, "service_unavailable"
        except Exception as e:
            return None, type(e).__name__

        if not isinstance(result, list):
            return None, "unexpected_response_type"

        if not result:
            return False, "no_data"

        return True, "has_data"

    @staticmethod
    def _get_hit_stats(hit_dates: list[str]) -> dict[str, int | str | None]:
        """Get hit-specific statistics for the current bidding zone.

        Args:
            hit_dates (list[str]): List of dates where data was found.

        Returns:
            dict[str, int | str | None]: Dictionary summarising the hit statistics.
        """
        if not hit_dates:
            return {
                "first_hit": None,
                "last_hit": None,
                "first_year": None,
                "last_year": None,
            }

        years = sorted({int(d[:4]) for d in hit_dates})
        return {
            "first_hit": min(hit_dates),
            "last_hit": max(hit_dates),
            "first_year": years[0],
            "last_year": years[-1],
        }

    # ------------------------------------------------------------------
    # Main entrypoint for printing the created mapping dict
    # ------------------------------------------------------------------
    def print_active_zone_metadata_dict(self) -> None:
        """Print ACTIVE_ZONE_METADATA dict to paste into rbc/energy/entsoe/mapping.py."""
        if not self.results_by_zone:
            self.results_by_zone = self._load_results()

        if not self.results_by_zone:
            logger.warning(
                "No JSON from which to extract the ACTIVE_ZONES_MAPPING dict!"
            )
            return

        print("ACTIVE_ZONES_MAPPING = {")
        for zone, meta in list(self.results_by_zone.items()):
            if not meta.get("has_any_data"):
                continue

            name = " / ".join(meta["zone_name"].keys())
            items = [f'"name": "{name}"', f'"start": {meta["first_year"]}']

            if meta.get("last_year", datetime.now().year) != datetime.now().year:
                items.append(f'"end": {meta["last_year"]}')

            print(f'    "{zone}": {{{", ".join(items)}}},')
        print("}")

    # ------------------------------------------------------------------
    # i/o helpers
    # ------------------------------------------------------------------
    def _load_results(self) -> dict[str, dict]:
        """Load existing results from disk if present.

        Returns:
            dict[str, dict]: Dictionary containing loaded bidding zone statistics.
        """
        if not self.results_path.is_file():
            return {}

        try:
            return json.loads(self.results_path.read_text())
        except json.JSONDecodeError:
            logger.warning(f"Existing results file '{self.results_path}' is invalid.")
            return {}

    def _save_results(self) -> None:
        """Save results dict to disk."""
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.results_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self.results_by_zone, indent=2, sort_keys=True))
        tmp_path.replace(self.results_path)

    def _print_summary(self) -> None:
        """Log a readable total summary."""
        results = list(self.results_by_zone.values())
        active = [r for r in results if r["has_any_data"]]
        inactive = [r for r in results if not r["has_any_data"]]

        logger.info("=== ENTSO-E ZONE PROBE SUMMARY ===")
        logger.info(f"Zones checked: {len(results)}")
        logger.info(f"Zones with sampled data: {len(active)}")
        logger.info(f"Zones with no sampled data: {len(inactive)}")

        logger.info("--- Zones with sampled data ---")
        for r in sorted(active, key=lambda x: (x["first_year"] or 9999, x["zone"])):
            logger.info(
                f"{r['zone']} | {r['zone_name']} | "
                f"hits={r['n_hits']} | first_year={r['first_year']} | last_year={r['last_year']}"
            )

        logger.info("--- Zones with no sampled data ---")
        for r in sorted(inactive, key=lambda x: x["zone"]):
            err = r["errors"]
            err_txt = (
                ", ".join(f"{k}:{v}" for k, v in sorted(err.items())) if err else "none"
            )
            logger.info(f"{r['zone']} | {r['zone_name']} | errors={err_txt}")


def parse_arguments() -> Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace parsed command line arguments.
    """
    parser = ArgumentParser(
        description="Get ENTSO-E bidding zones that provide energy generation data per unit."
    )
    parser.add_argument("-t", "--token", help="ENTSO-E API token.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for storing JSON results and logs.",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=list(range(2014, datetime.now().year + 1)),  # 2014 is the earliest
        help="Years to check. Default: 2014...current year",
    )
    parser.add_argument(
        "--dates-per-year",
        type=int,
        choices=[1, 2, 3],
        default=1,
        help="Number of sample dates per year to test. Default: 1",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing saved JSON if present.",
    )
    parser.add_argument(
        "--only-print-mapping",
        action="store_true",
        help="Don't get the data, only print the ACTIVE_ZONES_MAPPING dict from existing "
        "JSON results to copy-paste into 'rbc/energy/entsoe/mappings.py'.",
    )
    return parser.parse_args()


def main() -> None:
    """Coordinate getting active Entso-E EIC bidding zones."""
    args = parse_arguments()

    if not args.only_print_mapping and not args.token:
        raise ValueError("--token is required unless --only-print-mapping is used!")

    setup_logging(output_dir=args.output_dir)

    resume = args.resume or args.only_print_mapping
    collector = EntsoeBZCollector(
        token=args.token,
        output_dir=args.output_dir,
        years=args.years,
        dates_per_year=args.dates_per_year,
        resume=resume,
    )

    if args.only_print_mapping:
        collector.print_active_zone_metadata_dict()
        return

    collector.run()
    logger.info("Completed getting active Entso-E EIC bidding zones.")
    collector.print_active_zone_metadata_dict()


if __name__ == "__main__":
    main()
