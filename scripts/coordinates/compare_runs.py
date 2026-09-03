# scripts/coordinates/compare_runs.py
"""Compare two coordinate-finding runs to see what a matching change actually did.

Diffs a "before" run (typically an archive folder) against an "after" run (the live
output folder) for one operator, reporting how many EGEs gained, lost or changed their
match, which locator won, and how the fuzzy scores moved.

Run after every matching change so each step's effect is visible in isolation:
    $ python -m scripts.coordinates.compare_runs -s entsoe --detail 20
    $ python -m scripts.coordinates.compare_runs -s ons -b "path/to/first/run/"
"""

from argparse import ArgumentParser, Namespace
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import cast

import pandas as pd

from rbc.config.loader import load_config
from rbc.coordinates.mappings import OPERATOR_METADATA

UNMATCHED = "unmatched"


# ------------------------------------------------------------------
# Entry-points
# ------------------------------------------------------------------
def parse_arguments() -> Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Namespace with parsed command line arguments.
    """
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "-s",
        "--sysop",
        required=True,
        type=str,
        help="System operator name, e.g. 'ons' / 'entsoe'.",
    )
    parser.add_argument(
        "-b",
        "--before",
        type=Path,
        help=(
            "Earlier run directory. If None, defaults to newest CSVs in "
            "'coordinates/archive' folder or any subfolders that contains."
        ),
    )
    parser.add_argument(
        "-a",
        "--after",
        type=Path,
        help=(
            "Later run directory. If None, defaults to newest CSVs "
            "right in 'coordinates' folder (the live outputs from a run of "
            "coordinate_locator.py without output_dir specified)."
        ),
    )
    parser.add_argument(
        "-d",
        "--detail",
        type=int,
        default=10,
        help="How many changed EGEs to list. Defaults to 10.",
    )
    return parser.parse_args()


def main() -> None:
    """Coordinate the comparison and printing of details."""
    args = parse_arguments()

    before_dir = Path(args.before) if args.before else None
    after_dir = Path(args.after) if args.after else None

    if not after_dir:
        cfg = load_config(source=args.sysop)
        after_dir = Path(cfg.paths.dst_dir_raw, "coordinates")

    if not before_dir:
        archive_csvs = sorted(Path(after_dir, "archive").rglob("*.csv"))
        before_dir = (
            max(archive_csvs, key=lambda f: f.stat().st_ctime).parent
            if archive_csvs
            else None
        )

    if not before_dir or not after_dir:
        raise SystemExit(
            f"Missing before_dir '{before_dir}' or after_dir '{after_dir}'!"
        )

    print("before_dir:\t", before_dir)
    print("after_dir:\t", after_dir)

    coords_b, coords_a = (
        load(before_dir, "coordinates"),
        load(after_dir, "coordinates"),
    )
    fuzzy_b, fuzzy_a = (
        load(before_dir, "fuzzy_matches"),
        load(after_dir, "fuzzy_matches"),
    )

    tasks = sorted(set(coords_b) & set(coords_a))
    if not tasks:
        raise SystemExit(f"No shared tasks between {before_dir} and {after_dir}")

    for task in tasks:
        print(f"\n{'=' * 78}\n{args.sysop} / {task}\n{'=' * 78}")
        compare_coordinates(
            before=coords_b[task],
            after=coords_a[task],
            detail=args.detail,
            sysop=args.sysop,
        )

        if task in fuzzy_b and task in fuzzy_a:
            compare_fuzzy(before=fuzzy_b[task], after=fuzzy_a[task])
        else:
            print("\n  fuzzy candidates: not available in both runs")


# ------------------------------------------------------------------
# Primary helpers
# ------------------------------------------------------------------
def load(directory: Path, stem: str) -> dict[str, pd.DataFrame]:
    """Load every `<stem>_<task-descriptors>.csv` in a run dir, keyed by CSV descriptors.

    Task descriptors are of the shape: <tres>_<bz> (for ENTSOE) or <tres> (for ONS).
    Examples: '15min_10YRO-TEL------P' (ENTSOE) or '1h' (ONS).

    Args:
        directory (Path): Run directory holding the CSVs.
        stem (str): File stem to look for ("coordinates" or "fuzzy_matches").

    Returns:
        dict[str, pd.DataFrame]: Descriptor -> dataframe (empty dict if none found).
    """
    frames = {}
    for path in sorted(directory.glob(f"{stem}_*.csv")):
        task_descriptor = path.stem.removeprefix(f"{stem}_")
        frames[task_descriptor] = pd.read_csv(path, low_memory=False)
    return frames


def compare_coordinates(
    before: pd.DataFrame, after: pd.DataFrame, detail: int, sysop: str
) -> None:
    """Report coverage and per-EGE match changes between two runs of one zone.

    Args:
        before (pd.DataFrame): Coordinates dataframe from the earlier run.
        after (pd.DataFrame): Coordinates dataframe from the later run.
        detail (int): How many individual changed EGEs to list (0 to list none).
        sysop (str): Operator name, used to build readable per-EGE keys.
    """
    b_keys = _keys(before, sysop)
    b = pd.DataFrame({"key": b_keys, "src": _methods(before)}).set_index("key")
    a_keys = _keys(after, sysop)
    a = pd.DataFrame({"key": a_keys, "src": _methods(after)}).set_index("key")

    b_matched, a_matched = (b["src"] != UNMATCHED).sum(), (a["src"] != UNMATCHED).sum()
    print(f"  EGEs            {len(b):>6} -> {len(a):>6}")
    print(
        f"  matched         {b_matched:>6} -> {a_matched:>6}  "
        f"({a_matched - b_matched:+d}, {a_matched / max(len(a), 1):.1%} coverage)"
    )

    print("\n  match_source:")
    counts = (
        pd.DataFrame(
            {"before": b["src"].value_counts(), "after": a["src"].value_counts()}
        )
        .fillna(0)
        .astype(int)
    )
    counts["delta"] = counts["after"] - counts["before"]
    for match_source, row in counts.sort_values("after", ascending=False).iterrows():
        flag = "" if row["delta"] == 0 else f"  {row['delta']:+d}"
        print(f"    {match_source:<16} {row['before']:>6} -> {row['after']:>6}{flag}")

    shared = b.index.intersection(a.index)
    changed = shared[b.loc[shared, "src"].values != a.loc[shared, "src"].values]
    gained = shared[
        (b.loc[shared, "src"] == UNMATCHED).values
        & (a.loc[shared, "src"] != UNMATCHED).values
    ]
    lost = shared[
        (b.loc[shared, "src"] != UNMATCHED).values
        & (a.loc[shared, "src"] == UNMATCHED).values
    ]
    print(
        f"\n  changed matches  {len(changed):>6}  "
        f"(newly matched {len(gained)}, lost {len(lost)}, "
        f"switched source {len(changed) - len(gained) - len(lost)})"
    )

    if detail and len(changed):
        before_rows = before.set_index(b_keys)
        after_rows = after.set_index(a_keys)

        # a duplicate key makes .loc[key] return a frame instead of a row, so say which
        # run and which EGEs are at fault rather than failing obscurely further down
        for label, rows in (("before", before_rows), ("after", after_rows)):
            if not rows.index.is_unique:
                duplicates = rows.index[rows.index.duplicated()].unique().tolist()
                raise SystemExit(
                    f"Duplicate EGE keys in the {label} run: {duplicates[:5]}"
                )

        fuel_col = OPERATOR_METADATA[sysop].get("fuel_col")
        sysop_fuel = f"sysop.{fuel_col}" if fuel_col else None

        candidates = {
            key: (
                _matched_candidate(before_rows.loc[key], b.at[key, "src"]),
                _matched_candidate(after_rows.loc[key], a.at[key, "src"]),
            )
            for key in changed
        }

        # sort candidates by distance (longer jumps probably need reviewing most!)
        by_distance = sorted(
            candidates,
            key=lambda k: (
                _distance(
                    *(candidates[k][0][c] for c in ("lat", "lon")),
                    *(candidates[k][1][c] for c in ("lat", "lon")),
                )
                or -1.0
            ),
            reverse=True,
        )[:detail]

        print(f"\n  {len(by_distance)} of {len(changed)} changed, furthest move first:")
        width = max(
            (len(_describe_name(c)) for k in by_distance for c in candidates[k]),
            default=0,
        )

        for key in by_distance:
            was, now = candidates[key]
            moved = _distance(was["lat"], was["lon"], now["lat"], now["lon"])
            target_fuel = after_rows.loc[key].get(sysop_fuel) if sysop_fuel else None
            header = f"    {key}"
            if target_fuel is not None and not pd.isna(target_fuel):
                header += f' - "{target_fuel}"'
            print(header)
            for label, cand, src in (
                ("was", was, b.at[key, "src"]),
                ("now", now, a.at[key, "src"]),
            ):
                name = _describe_name(cand)
                details = _describe_details(cand)
                print(f"        {label}  {src:<14} {name:<{width}}  {details}".rstrip())
            if moved is not None:
                print(f"        moved {moved:,.1f} km")  # how much an EGE has moved


def compare_fuzzy(before: pd.DataFrame, after: pd.DataFrame) -> None:
    """Report how the fuzzy candidate pool (debug file) and its scores moved between two runs.

    Args:
        before (pd.DataFrame): fuzzy_matches dataframe from the earlier run.
        after (pd.DataFrame): fuzzy_matches dataframe from the later run.
    """
    print("\n  fuzzy candidates:")
    for label, df in (("before", before), ("after", after)):
        scored = df[df["candidate.score"].notna()]
        targets = df["target.idx"].nunique() if "target.idx" in df else float("nan")
        winners = (
            df["candidate.is_winner"].sum() if "candidate.is_winner" in df else "n/a"
        )
        print(
            f"    {label:<7} rows {len(df):>7}  targets {targets:>5}  "
            f"winners {winners:>5}  median score "
            f"{scored['candidate.score'].median() if len(scored) else float('nan'):.1f}"
        )

    if "candidate.is_winner" in after and "candidate.is_winner" in before:
        for label, df in (("before", before), ("after", after)):
            won = df[df["candidate.is_winner"].fillna(False)]
            if len(won):
                print(
                    f"    {label:<7} winning score: min {won['candidate.score'].min():.1f}"
                    f"  median {won['candidate.score'].median():.1f}"
                    f"  max {won['candidate.score'].max():.1f}"
                )


# ------------------------------------------------------------------
# Secondary helpers
# ------------------------------------------------------------------
def _keys(df: pd.DataFrame, sysop: str) -> pd.Series:
    """Build a readable, unique per-EGE key from the operator's own name/code columns.

    OPERATOR_METADATA used to identify columns of EGE names and codes. These are combined
    to create a Series of unique keys: "<name> [<code>]" (e.g. "Flores 3 [FLOR3]").

    Args:
        df (pd.DataFrame): Coordinates dataframe from one run.
        sysop (str): System operator name, used to look up its column definitions.

    Returns:
        pd.Series: Row key, falling back to the row index if no sysop column is found.
    """
    meta = OPERATOR_METADATA[sysop]
    name_col = f"sysop.{meta.get('entity_col')}"
    code_col = f"sysop.{meta.get('code_col')}"

    if name_col in df.columns:
        names = df[name_col].astype(str)
        if code_col in df.columns:
            return names + " [" + df[code_col].astype(str) + "]"
        return names

    # no configured name column in this run: any unique sysop column beats the bare index
    for col in df.columns:
        if col.startswith("sysop.") and df[col].is_unique and df[col].notna().all():
            return df[col].astype(str)
    return pd.Series(df.index.astype(str), index=df.index)


def _methods(df: pd.DataFrame) -> pd.Series:
    """Return each row's match_source methods, with unmatched rows labeled explicitly.

    Args:
        df (pd.DataFrame): Coordinates dataframe from one run.

    Returns:
        pd.Series: match_source per row.
    """
    if "match_source" not in df:
        return pd.Series(UNMATCHED, index=df.index)
    return df["match_source"].fillna(UNMATCHED).replace("", UNMATCHED)


def _matched_candidate(row: pd.Series, match_source: str) -> dict[str, object]:
    """Pull the winning candidate's details out of its `<locator>.*` columns.

    Args:
        row (pd.Series): One EGE's row from a coordinates dataframe.
        match_source (str): That row's match_source (e.g. "gem_fuzzy", "osm_sibling_of:...").

    Returns:
        dict[str, object]: name, source_id, score, fueltype, fuel level, lat and lon of
            the winning candidate.
    """
    locator = match_source.split("_")[0]  # gem_fuzzy -> gem, gem_sibling -> gem
    get = lambda field: row.get(f"{locator}.{field}")  # noqa: E731

    # the sibling step inherits coordinates, recording its donor in match_source instead
    name = get("name")
    if "_sibling" in match_source:
        raw = str(row.get("sibling.match_source") or "")
        name = raw.split("_sibling_of:")[-1] or None

    return {
        "name": name,
        "source_id": get("source_id"),
        "score": get("match_score"),
        "fueltype": get("fueltype"),  # decides whether a candidate is vetoed
        "fuel_level": row.get("fuel_type_match_level"),
        "lat": row.get("lat"),
        "lon": row.get("lon"),
    }


def _describe_name(candidate: dict[str, object]) -> str:
    """Render a matched candidate's name and source id, for the name column.

    Args:
        candidate (dict[str, object]): Candidate details from _matched_candidate.

    Returns:
        str: Formatted "name [id]", or "?" when nothing was matched.
    """
    if candidate["name"] is None and candidate["lat"] is None:
        return "?"

    name = str(candidate["name"] or "?")[:40]
    if candidate["source_id"] is not None and not pd.isna(candidate["source_id"]):
        return f"{name} [{candidate['source_id']}]"
    return name


def _describe_details(candidate: dict[str, object]) -> str:
    """Render a matched candidate's score, coordinates and fuel type.

    Args:
        candidate (dict[str, object]): Candidate details from _matched_candidate.

    Returns:
        str: Formatted '@score (lat, lon), "fueltype" (level)', omitting what is missing.
    """
    parts = []
    if candidate["score"] is not None and not pd.isna(candidate["score"]):
        parts.append(f"@{cast(float, candidate['score']):.1f}")
    if candidate["lat"] is not None and not pd.isna(candidate["lat"]):
        parts.append(
            f"({cast(float, candidate['lat']):.3f}, "
            f"{cast(float, candidate['lon']):.3f}),"
        )

    fueltype, level = candidate.get("fueltype"), candidate.get("fuel_level")
    if fueltype is not None and not pd.isna(fueltype):
        parts.append(f'"{str(fueltype)[:38]}"')
        if level is not None and not pd.isna(level):
            parts.append(f"({level})")
    return " ".join(parts).rstrip(",")


def _distance(lat1: object, lon1: object, lat2: object, lon2: object) -> float | None:
    """Great-circle distance between two matched coordinates in km, if both are present.

    Args:
        lat1 (object): Latitude of the earlier run's match.
        lon1 (object): Longitude of the earlier run's match.
        lat2 (object): Latitude of the later run's match.
        lon2 (object): Longitude of the later run's match.

    Returns:
        float | None: Distance in km, or None if either coordinate pair is missing.
    """
    values = [lat1, lon1, lat2, lon2]
    if any(v is None or pd.isna(v) for v in values):
        return None

    phi1, lam1, phi2, lam2 = (radians(cast(float, v)) for v in values)
    haversine = (
        sin((phi2 - phi1) / 2) ** 2
        + cos(phi1) * cos(phi2) * sin((lam2 - lam1) / 2) ** 2
    )
    return 2 * 6371.0 * asin(sqrt(haversine))


if __name__ == "__main__":
    main()
