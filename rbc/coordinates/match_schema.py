"""Match schema-related functionality."""

from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Callable

import pandas as pd

from rbc.coordinates.utils.tokenizer import NameTokenizer
from rbc.coordinates.utils.values import strip_str

if TYPE_CHECKING:
    from rbc.coordinates.matcher import NameMatcher


@dataclass(frozen=True)
class LocatorAdapter:
    """Column-mapping config that lets one candidate builder serve any source.

    Replaces hardcoded candidate building per locator source with a single generic builder
    (see ``NameMatcher._build_candidates``).
    """

    # todo: Several attributes are not necessary, as the MatchCandidate elements they
    #  feed are not used anywhere. These are: "other_names_col", "confidence_fn"

    source: str  # locator name 'ppdb' (= ppm/osmpp), 'gem', 'osm'
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
    get_df=lambda m: getattr(m.gem_locator, "df", None),
    name_col="plant_name",
    other_names_col="other_names",  # todo: these seem to be unused?
    id_col="gem_unit_id",
    country_col="Country",
    status_col="Status",
    url_col="wiki_url",
    extra_cols=(),
)

# todo: confidence def means PPDB all non-entsoe operators have "medium" confidence level
PPDB_ADAPTER = LocatorAdapter(
    source="ppdb",
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
    get_df=lambda m: m.osm_df,  # duplicated rows for each alt name (s. osm_api.py)
    name_col="Name",
    other_names_col="",
    id_col="OSM_ID",
    country_col=None,  # no country column; relies on the matrix-level filter
    status_col="Status",
    url_col="OSM_URL",
    extra_cols=("OSM_Type", "OSM_Geometry"),
)


@dataclass
class MatchCandidate:
    """A single matching candidate from a data source."""

    # todo: Several attributes are never used. Decide whether to keep or remove! They include:
    #  "other_names"

    name: str
    norm_name: str = field(metadata={"internal": True})  # actually tokenized & rejoined
    source: str = field(metadata={"internal": True})  # 'ppdb' (= ppm/osmpp)/'gem'/'osm'
    source_id: str | None
    fueltype: str | None
    capacity: str | None
    status: str | None
    url: str | None
    lat: float | None
    lon: float | None
    country: str | None
    other_names: str = field(default="", metadata={"internal": True})  # ,-sep alt names
    extras: dict = field(default_factory=dict, metadata={"internal": True})  # more data
    match_score: float | None = field(default=0.0)

    @classmethod
    def from_row(
        cls, row: pd.Series, adapter: LocatorAdapter, tok: NameTokenizer | None = None
    ) -> "MatchCandidate | None":
        """Build a matching candidate from a locator row, using the adapter's column mapping.

        Args:
            row (pd.Series): Row of a dataframe.
            adapter (LocatorAdapter): Adapter of the locator.
            tok (NameTokenizer): NameTokenizer for name normalization, if required.

        Returns:
            MatchCandidate | None: MatchCandidate if the row has a name, otherwise None.
        """
        name = strip_str(row[adapter.name_col])
        if name is None:
            return None

        # tokenize name for better cross-language matching (expands abbreviated terms)
        tokenized_name = " ".join(tok.tokenize(name)) if tok is not None else name

        other_names = ""
        if adapter.other_names_col:
            other_names = strip_str(row.get(adapter.other_names_col)) or ""

        extras = {c: strip_str(row.get(c)) for c in adapter.extra_cols}

        return cls(
            name=name,
            norm_name=tokenized_name,
            source=adapter.source,
            source_id=strip_str(row.get(adapter.id_col)),
            fueltype=strip_str(row[adapter.fueltype_col]),
            capacity=strip_str(row.get(adapter.capacity_col)),
            status=strip_str(row.get(adapter.status_col)),
            url=strip_str(row.get(adapter.url_col)),
            lat=float(row[adapter.lat_col]),
            lon=float(row[adapter.lon_col]),
            country=strip_str(row.get(adapter.country_col)),
            other_names=other_names,
            extras=extras,
            match_score=None,
        )

    def to_dict(self) -> dict[str, object]:
        """Maps candidate attribute values to column names to add to the output DataFrame.

        Attributes marked as "internal" or with a `None` values are excluded. Omitting `None`
        ensures columns are only created for attributes actually provided by a locator.

        Returns:
            dict[str, object]: Dictionary of column headers and their values
        """
        cols = {
            f"{self.source}.{f.name}": val
            for f in fields(self)
            if not f.metadata.get("internal")
            and (val := getattr(self, f.name)) is not None
        }
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
    all_target_variants: list[str]
    top_matches: list[tuple[MatchCandidate, float]]  # best 10 (score > 5 below thresh)

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
            "target.variants": ", ".join(self.all_target_variants),
            "target.fueltype": target_fueltype if target_fueltype is not None else "-",
        }

        # If there are matched candidates, generate one dict row per match
        list_of_dicts = []
        if self.top_matches:
            self.top_matches.sort(key=lambda x: x[1], reverse=True)
            for cand, score in self.top_matches:
                locator = cand.source
                cand_dict = {
                    "candidate." + k.split(f"{locator}.")[-1]: v
                    for k, v in cand.to_dict().items()
                    if k.startswith(f"{locator}.") and not any(map(str.isupper, k))
                }
                list_of_dicts.append(
                    {
                        **base,
                        "locator": locator,
                        "candidate.score": round(score, 2),
                        **cand_dict,
                    }
                )
            return list_of_dicts

        # Fallback for when all_matches is empty
        return [{**base, "locator": None, "candidate.score": None, **{}}]
