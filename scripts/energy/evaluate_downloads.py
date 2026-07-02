#!/usr/bin/env python
"""EVALUATE DOWNLOADERS SCRIPT.

Evalute if the energy downloaders ran completely.
"""
from argparse import ArgumentParser, Namespace
from collections import defaultdict
from datetime import datetime
from dateutil.relativedelta import relativedelta
from itertools import groupby
import pickle
from pathlib import Path
from typing import Optional

from rbc.config.loader import load_config, CONFIGS_DIR
from rbc.config.schema import SCHEMA_REGISTRY, Paths

SOURCES = [p.stem for p in sorted(Path(CONFIGS_DIR, "energy").glob("*.yaml"))]

DATE_CONFIGS = {
    7:  {"fmt": "%Y-%m",    "step": relativedelta(months=1)},  # Monthly
    10: {"fmt": "%Y-%m-%d", "step": relativedelta(days=1)}     # Daily
}


# ===============================
# COORDINATION
# ===============================
def parse_arguments() -> Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace with parsed command line arguments.
    """
    parser = ArgumentParser(prog="Energy source evaluation")
    parser.add_argument(
        "-s",
        "--sources",
        nargs="+",
        type=str,
        default=SOURCES,
        help=f"List of sources to assess, e.g. 'adme'. Default: {SOURCES}",
    )
    parser.add_argument(
        "-a",
        "--print_all",
        action="store_true",
        default=None,
        help="Print all 'status.pickle' entries. Default: False (only failures/0 are printed)"
    )  
    return parser.parse_args()


def main():
    """Coordinating energy source download evaluation."""
    args = parse_arguments()

    for source in args.sources:
        print(f"\n===== EVALUATING: {source} =====")
        cfg = load_config(source=source)

        source_path = Path(cfg.paths.dst_dir_raw)
        if not source_path.is_dir():
            print(f"[WARN] Directory not found: {source_path}")
            print(f"\n===== FINISHED: {source} =====\n")
            continue

        expected_dates = get_pickle_overview(source_path, args.print_all)
        get_download_overview(source_path, expected_dates)

        print(f"\n===== FINISHED: {source} =====\n")


# ===============================
# CENTRAL FUNCTIONS
# ===============================
def get_pickle_overview(source_dir: Path, print_all: bool = False) -> set[str]:
    """Print the contents of the 'status.pickle' file.

    Args:
        source_dir (Path): Path to the source root folder, which should contain the pickle.
        print_all (bool, Optional): Print all entries. Defaults to False (only values=0 printed).

    Returns:
        expected_dates (set[str]): Expected dates according to the pickle file.
    """
    print("\n----- PICKLE OVERVIEW -----")
    expected_dates = set()

    pickle_path = Path(source_dir, "status.pickle")
    if not pickle_path.is_file():
        print(f"[WARN] Pickle file 'status.pickle' not found: {pickle_path}")
        return expected_dates

    print(f"Path:\t{pickle_path}")
    with open(pickle_path, "rb") as f:
        data = pickle.load(f)

    if not hasattr(data, "items"):
        print("[WARN] Pickle content is not a dict-like object with .items()")
        return expected_dates

    status_groups = defaultdict(list)

    for key, value in data.items():
        parts = dict(item.split("=") for item in key.split("|"))
        if "date" in parts:
            date_str = parts["date"]

            # add all dates for later verification
            expected_dates.add(date_str)
                        
            #  group for printing if flag is set or the value is a failure (= 0)
            if print_all or str(value) == "0":
                # construct trailing key attributes like temporal resolution (excl. date)
                meta_str = "|".join(f"{k}={v}" for k, v in parts.items() if k != "date")
                group_key = (str(value), meta_str)
                status_groups[group_key].append(date_str)

    # print grouped summaries using compact formatter
    for (status, meta), dates in sorted(status_groups.items()):
        header_suffix = f" | {meta}" if meta else ""
        print(f"\t---> Status: {status}{header_suffix} ({len(dates)} entries):")
        print(format_gaps_compactly(dates))

    return expected_dates


def get_download_overview(source_dir: Path, pickle_exp_dates: set[str]) -> None:
    """Print an overview of the downloaded data.

    Args:
        source_dir (Path): Path to the source root folder, which should contain the CSV/JSONs.
        pickle_exp_dates (set[str]): Expected dates according to the pickle file.
    """
    print("\n----- DOWNLOADED FILES OVERVIEW -----")

    all_csv_paths = sorted(source_dir.rglob("*.csv"))
    all_json_paths = sorted(source_dir.rglob("*.json"))
    all_paths = all_csv_paths if all_csv_paths else all_json_paths

    if not all_paths:
        print(f"[WARN] No csv or json files found in: {source_dir}")
        return

    files_grouped_by_parent = defaultdict(list)
    for p in all_paths:
        files_grouped_by_parent[p.parent].append(p.stem)

    for key, values in files_grouped_by_parent.items():
        print(f"Path:\t{key}")
        values.sort()

        # 1. find gaps based strictly on the files present in the directory
        start_date, end_date = values[0], values[-1]
        derived_exp_dates = generate_expected_range(start_date, end_date)
        timeline_gaps = derived_exp_dates - set(values)

        print(f"\t---> {len(timeline_gaps)} data gaps found based on expected timeline "
              f"from the directory!")
        if timeline_gaps:
            print(format_gaps_compactly(list(timeline_gaps)))
            # print(f"\t\tGaps: {sorted(timeline_gaps)}")

        # 2. cross-reference with exptected dates from pickle
        date_len = len(start_date)
        local_pickle_exp_dates = {d for d in pickle_exp_dates if len(d) == date_len}
        if local_pickle_exp_dates:
            pickle_gaps = local_pickle_exp_dates - set(values)
            print(f"\t---> {len(pickle_gaps)} data gaps found based on expected files "
                  f"from the 'status.pickle'!")
            if pickle_gaps:
                print(format_gaps_compactly(list(pickle_gaps)))
                # print(f"\t\t{sorted(pickle_gaps)}")


# ===============================
# HELPER FUNCTIONS
# ===============================
def generate_expected_range(start_str: str, end_str: str) -> set[str]:
    """Generate a complete set of date strings between start and end inclusive.

    Args:
        start_str (str): The start date string to parse.
        end_str (str): The end date string to parse.

    Returns:
        generated_range (set[str]): Complete set of expected date strings from start to end.
    """
    date_cfg = DATE_CONFIGS[len(start_str)]
    fmt, step = date_cfg["fmt"], date_cfg["step"]
            
    start_dt = datetime.strptime(start_str, fmt)
    end_dt = datetime.strptime(end_str, fmt)

    generated_range = set()
    current_dt = start_dt
    while current_dt <= end_dt:
        generated_range.add(current_dt.strftime(fmt))
        current_dt += step

    return generated_range


def format_gaps_compactly(gaps_list: list[str]) -> str:
    """Format a list of date strings into human-readable ranges grouped by year.
        
    Example output: 
        2020: '2020-07-15', '2020-08-09', '2020-08-15' to '2020-08-16'
        2024: '2024-11-05' to '2026-06-17'

    Args:
        gaps_list (list): List of gap dates to be formatted.

    Returns:
        str: Formatted gap dates ready for printing.
    """

    date_cfg = DATE_CONFIGS[len(gaps_list[0])]
    fmt, step = date_cfg["fmt"], date_cfg["step"]

    # parse to datetime objects to compute consecutive sequences
    dt_list = sorted([datetime.strptime(g, fmt) for g in gaps_list])
        
    # group consecutive elements by tracking (date - index * step)
    ranges = []
    for _, g in groupby(enumerate(dt_list), lambda x: x[1] - x[0] * step):
        group = list(g)
        start = group[0][1].strftime(fmt)
        end = group[-1][1].strftime(fmt)
                
        if start == end:
            ranges.append(f"'{start}'")
        else:
            ranges.append(f"'{start}' to '{end}'")
                        
    # group the final range strings by year (first 4 characters) for clean output
    lines = []
    for year, items in groupby(ranges, lambda x: x[1:5]):
        lines.append(f"\t\t{year}: {', '.join(items)}")
                
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()

