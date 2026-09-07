"""Match schema-related functionality."""

from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Callable

import pandas as pd
from loguru import logger

from rbc.coordinates.utils.tokenizer import NameTokenizer
from rbc.coordinates.utils.values import strip_str

if TYPE_CHECKING:
    from rbc.coordinates.matcher import NameMatcher


@dataclass(frozen=True)
class LocatorAdapter:
    """Column-mapping config that lets one candidate builder serve any locator source.

    Replaces hardcoded candidate building per locator source with a single generic builder
    (see ``NameMatcher._build_candidates``).
    """

    source: str  # locator name 'ppdb' (= ppm/osmpp), 'gem', 'osm'
    reliability: int  # reliability score for name matching (the higher, the better!)
    get_df: Callable[["NameMatcher"], pd.DataFrame | None]
    name_col: str
    other_names_col: str | None  # comma-separated alternative names (only GEM)
    id_col: str
    country_col: str | None  # None if the source has no country column (e.g. OSM)
    status_col: str | None
    url_col: str | None
    extra_cols: tuple[str, ...]  # extra columns of data to propagate (only OSM)
    fueltype_col: str = "Fueltype"
    capacity_col: str = "Capacity"
    lat_col: str = "lat"
    lon_col: str = "lon"


GEM_ADAPTER = LocatorAdapter(
    source="gem",
    reliability=3,
    get_df=lambda m: getattr(m.gem_locator, "df", None),
    name_col="plant_name",
    other_names_col="other_names",  # todo: these seem to be unused?
    id_col="gem_unit_id",
    country_col="Country",
    status_col="Status",
    url_col="wiki_url",
    extra_cols=(),
)

PPDB_ADAPTER = LocatorAdapter(
    source="ppdb",
    reliability=2,
    get_df=lambda m: getattr(m.ppdb_locator, "df", None),
    name_col="Name",
    other_names_col="",
    id_col="id",
    country_col="Country",
    status_col=None,
    url_col=None,
    extra_cols=(),
)

OSM_ADAPTER = LocatorAdapter(
    source="osm",
    reliability=1,
    get_df=lambda m: m.osm_df,  # duplicated rows for each alt name (s. osm_api.py)
    name_col="Name",
    other_names_col="",
    id_col="OSM_ID",
    country_col=None,  # no country column; relies on the matrix-level filter
    status_col="Status",
    url_col="OSM_URL",
    extra_cols=("OSM_Type", "OSM_Geometry"),
)

# locator adapters ordered by their reliability score
LOCATOR_ADAPTERS = sorted(
    [GEM_ADAPTER, PPDB_ADAPTER, OSM_ADAPTER], key=lambda a: a.reliability, reverse=True
)
LOCATOR_RELIABILITY: dict[str, int] = {
    a.source: a.reliability for a in LOCATOR_ADAPTERS
}


@dataclass
class MatchCandidate:
    """A single target EGE candidate from a locator source.

    One MatchCandidate = one name variant of a physical EGE. If an EGE has:
    - a single name: there is one MatchCandidate for it (`primary_name`=`name`)
    - multiple names (primary name + any `other_names`): each has their own MatchCandidate
        - only `name`, `norm_name`, `wt_string` reflect THIS variant.
        - all other parameters are defined identically
    """

    name: str  # name of THIS variant
    primary_name: str  # authoritative name of the EGE
    norm_name: str = field(metadata={"internal": True})  # tok str of THIS variant
    wt_string: str = field(metadata={"internal": True})  # WeightedTokens str of THIS
    source: str = field(metadata={"internal": True})  # 'ppdb' (= ppm/osmpp)/'gem'/'osm'
    source_id: str
    fueltype: str | None
    capacity: str | None
    status: str | None
    url: str | None
    lat: float | None
    lon: float | None
    country: str | None
    extras: dict = field(default_factory=dict, metadata={"internal": True})  # more data

    @property
    def ege_key(self) -> tuple[str, str]:
        """Identity of the locator's physical EGE (shared across variants).

        Returns:
            tuple[str, str]: Identity key for the physical EGE.
        """
        return self.source, self.source_id

    @classmethod
    def from_row(
        cls, row: pd.Series, loc: LocatorAdapter, tok: NameTokenizer | None = None
    ) -> list["MatchCandidate"]:
        """Builds one MatchCandidate per name variant (primary + other_names).

        Uses the provided locator row and the adapter's column mapping to get the relevant
        information. Uses the tokenizer for name normalization (req for later processing).

        Args:
            row (pd.Series): Row of a dataframe.
            loc (LocatorAdapter): Adapter of the locator.
            tok (NameTokenizer): NameTokenizer for name normalization, if required.

        Returns:
            list[MatchCandidate]: List of MatchCandidates for the row with primary-name
                candidate first, then one per other_name. Empty list if no primary name.
        """
        primary_name = strip_str(row[loc.name_col])
        if primary_name is None:
            return []

        source_id = strip_str(row.get(loc.id_col))
        if source_id is None:
            logger.warning(
                f"Skipping {loc.source} row with missing {loc.id_col} for "
                f"{primary_name}"
            )
            return []

        other_names = row.get(loc.other_names_col, "")
        if not isinstance(other_names, str):  # GEM's other_names can be NAType objects
            other_names = ""

        name_variants: list[str] = [primary_name] + [
            n for n in (strip_str(n) for n in other_names.split(",")) if n is not None
        ]

        source = loc.source
        fueltype = strip_str(row[loc.fueltype_col])
        capacity = strip_str(row.get(loc.capacity_col))
        status = strip_str(row.get(loc.status_col))
        url = strip_str(row.get(loc.url_col))
        lat = float(row[loc.lat_col])
        lon = float(row[loc.lon_col])
        country = strip_str(row.get(loc.country_col))
        extras = {c: strip_str(row.get(c)) for c in loc.extra_cols}

        candidates: list[MatchCandidate] = []
        for name in name_variants:
            tok_name = " ".join(tok.tokenize(name)) if tok is not None else name
            wt_name = tok.weighted_tokenize(name).as_str() if tok is not None else ""
            candidates.append(
                cls(
                    name=name,
                    norm_name=tok_name,
                    wt_string=wt_name,
                    primary_name=primary_name,
                    source=source,
                    source_id=source_id,
                    fueltype=fueltype,
                    capacity=capacity,
                    status=status,
                    url=url,
                    lat=lat,
                    lon=lon,
                    country=country,
                    extras=extras,
                )
            )

        return candidates

    @classmethod
    def primary_from_row(
        cls, row: pd.Series, loc: LocatorAdapter
    ) -> "MatchCandidate | None":
        """Get the primary match candidate from a locator row with the adapter's col mapping.

        Args:
            row (pd.Series): Row of a dataframe.
            loc (LocatorAdapter): Adapter of the locator.

        Returns:
            MatchCandidate | None: MatchCandidate if the row has a primary name, else None.
        """
        candidates = cls.from_row(row, loc)
        return candidates[0] if candidates else None

    def to_dict(self) -> dict[str, object]:
        """Maps candidate attribute values to column names to add to the output DataFrame.

        Attributes marked as "internal" or with a `None` values are excluded. Omitting `None`
        ensures columns are only created for attributes actually provided by a locator.

        Returns:
            dict[str, object]: Dictionary of column headers and their values
        """
        cols: dict[str, object] = {}
        for f in fields(self):
            if f.metadata.get("internal") or f.name == "primary_name":
                continue

            val = getattr(self, f.name)
            if val is None:
                continue

            cols[f"{self.source}.{f.name}"] = val
            if f.name == "name":
                cols[f"{self.source}.primary_name"] = (
                    self.primary_name if self.primary_name != self.name else None
                )

        extras = {
            f"{self.source}.{key.removeprefix('OSM_')}": val
            for key, val in self.extras.items()
            if val is not None
        }
        return {**cols, **extras}


@dataclass
class MatchResult:
    """Result of a name matching operation."""

    matched: bool
    candidate: MatchCandidate | None
    score: float
    target_variants: list[str]
    target_wt_strings: list[str]  # WeightedTokens.as_str of all target_variants
    top_matches: list[tuple[MatchCandidate, float]]  # best 10 matches

    def to_dicts(
        self, target_idx: int | None = None, target_fueltype: str | None = None
    ) -> list[dict[str, object]]:
        """Maps match results into a list of dicts, creating one row per entry in top_matches.

        Args:
            target_idx (int | None): Index of the target EGE to include in the dict.
                Defaults to None.
            target_fueltype (str | None): Fuel type of the target EGE to include in the dict.
                Defaults to None.

        Returns:
            list[dict[str, object]]: List of row dictionaries suitable for DataFrame creation.
        """
        base = {
            "target.idx": target_idx if target_idx is not None else "-",
            "matched": self.matched,
            "target.variants": " | ".join(self.target_variants),
            "target.fueltype": target_fueltype if target_fueltype is not None else "-",
            "target.weighted_tokens": " | ".join(self.target_wt_strings),
        }

        # If there are matched candidates, generate one dict row per match
        list_of_dicts = []
        if self.top_matches:
            for cand, score in self.top_matches:
                locator = cand.source
                cand_dict = {
                    "candidate." + k.split(f"{locator}.")[-1]: v
                    for k, v in cand.to_dict().items()
                    if k.startswith(f"{locator}.")
                    and not any(map(str.isupper, k))
                    and not k.endswith(".country")
                }
                list_of_dicts.append(
                    {
                        **base,
                        "locator": locator,
                        "candidate.is_winner": "True"
                        if cand is self.candidate
                        else None,
                        "candidate.score": round(score, 2),
                        "candidate.weighted_tokens": cand.wt_string,
                        **cand_dict,
                    }
                )
            return list_of_dicts

        # Fallback for when all_matches is empty
        return [{**base, "locator": None, "candidate.score": None, **{}}]
