"""Match schema-related functionality."""

from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Callable

import pandas as pd

from rbc.coordinates.utils.tokenizer import NameTokenizer
from rbc.coordinates.utils.values import strip_str

if TYPE_CHECKING:
    from rbc.coordinates.matcher import NameMatcher


@dataclass(frozen=True)
class SourceAdapter:
    """Column-mapping config that lets one candidate builder serve any source.

    Replaces hardcoded candidate building per locator source with a single generic builder
    (see ``NameMatcher._build_candidates``).
    """

    # todo: Several attributes are not necessary, as the MatchCandidate elements they
    #  feed are not used anywhere. These are: "other_names_col", "confidence_fn"

    source: str  # 'ppdb' (= ppm/osmpp), 'gem', 'osm'
    get_df: Callable[["NameMatcher"], pd.DataFrame | None]
    name_col: str
    other_names_col: str | None  # comma-separated alternative names (only GEM)
    id_col: str
    country_col: str | None  # None if the source has no country column (e.g. OSM)
    status_col: str | None
    url_col: str | None
    extra_cols: tuple[str, ...]  # extra columns of data to propagate (only OSM)
    confidence_fn: Callable[[pd.Series], str]
    fueltype_col: str = "Fueltype"
    capacity_col: str = "Capacity"
    lat_col: str = "lat"
    lon_col: str = "lon"


GEM_ADAPTER = SourceAdapter(
    source="gem",
    get_df=lambda m: getattr(m.gem_locator, "df", None),
    name_col="plant_name",
    other_names_col="other_names",  # todo: these seem to be unused?
    id_col="gem_unit_id",
    country_col="Country",
    status_col="Status",
    url_col="wiki_url",
    extra_cols=(),
    confidence_fn=lambda row: "high",
)

# todo: confidence def means PPDB all non-entsoe operators have "medium" confidence level
PPDB_ADAPTER = SourceAdapter(
    source="ppdb",
    get_df=lambda m: getattr(m.ppdb_locator, "df", None),
    name_col="Name",
    other_names_col="",
    id_col="id",
    country_col="Country",
    status_col=None,
    url_col=None,
    extra_cols=(),
    confidence_fn=lambda row: "high" if pd.notna(row.get("EIC")) else "medium",
)

OSM_ADAPTER = SourceAdapter(
    source="osm",
    get_df=lambda m: m.osm_df,  # duplicated rows for each alt name (s. osm_api.py)
    name_col="Name",
    other_names_col="",
    id_col="OSM_ID",
    country_col=None,  # no country column; relies on the matrix-level filter
    status_col="Status",
    url_col="OSM_URL",
    extra_cols=("OSM_Type", "OSM_Geometry"),
    confidence_fn=lambda row: "medium",
)


@dataclass
class MatchCandidate:
    """A single matching candidate from a data source."""

    # todo: Several attributes are never used. Decide whether to keep or remove! They include:
    #  "match_score", "confidence", "other_names"

    name: str
    norm_name: str = field(metadata={"internal": True})  # actually tokenized & rejoined
    source: str = field(
        metadata={"internal": True}
    )  # 'ppdb' (= ppm/osmpp), 'gem', 'osm'
    source_id: str | None
    fueltype: str | None
    capacity: str | None
    status: str | None
    url: str | None
    lat: float | None
    lon: float | None
    country: str | None
    other_names: str = field(
        default="", metadata={"internal": True}
    )  # alt names (,-sep)
    extras: dict = field(
        default_factory=dict, metadata={"internal": True}
    )  # extra data
    match_score: float = field(default=0.0, metadata={"internal": True})
    confidence: str = field(default="high", metadata={"internal": True})  # 3 levels

    @classmethod
    def from_row(
        cls, row: pd.Series, adapter: SourceAdapter, tok: NameTokenizer | None = None
    ) -> "MatchCandidate | None":
        """Build a matching candidate from a locator row, using the adapter's column mapping.

        Args:
            row (pd.Series): Row of a dataframe.
            adapter (SourceAdapter): Adapter of the locator.
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
            confidence=adapter.confidence_fn(row),
            other_names=other_names,
            extras=extras,
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

    # todo: Several attributes are never used. Decide whether to keep or remove! They include:
    #  "variants_tried", "top_candidates"

    matched: bool
    candidate: MatchCandidate | None
    score: float
    variants_tried: list[str]
    top_candidates: list[MatchCandidate]  # Top 5 for debugging
