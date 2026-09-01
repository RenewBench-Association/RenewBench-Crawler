"""DATA SOURCE CONFIGURATION.

Schema definitions for different data sources.
"""

from pathlib import Path
from typing import Literal, Type

from pydantic import BaseModel, field_validator


# ----------------------------------
# General schemas
# ----------------------------------
class Paths(BaseModel):
    """Filesystem paths used by a data source.

    Attributes:
        dst_dir_raw (Path): Destination directory for raw data output.
    """

    dst_dir_raw: Path


class AccessAPI(BaseModel):
    """Access settings for a data source requiring API key / security token.

    Attributes:
        api_key (str): API key.
    """

    api_key: str


class AccessAccount(BaseModel):
    """Access settings for a data source requiring an account username & password.

    Attributes:
        username (str): Account username.
        password (str): Account password.
    """

    username: str
    password: str


# ----------------------------------
# General schema validators
# ----------------------------------
class PathValidation:
    """Validator for Path fields to ensure they are safe and writable."""

    @field_validator("paths", mode="after")
    @classmethod
    def check_paths(cls, paths: BaseModel) -> BaseModel:
        """Validate that destination directories are accessible.

        Args:
            paths (BaseModel): Parsed paths configuration.

        Returns:
            BaseModel: The validated paths object.

        Raises:
            ValueError: If the path is not writable.
        """
        for field, path in paths.model_dump().items():
            if not isinstance(path, (str, Path)):
                continue

            try:
                Path(path).mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError) as e:
                raise ValueError(
                    f"Path '{field}' ('{path}') is not writable or cannot be created. "
                    f"System error: {e}"
                )

        return paths


class AccessValidation:
    """Validator for "access" fields to ensure strings contain non-placeholder content."""

    @field_validator("access", mode="after")
    @classmethod
    def check_access_values(cls, access: BaseModel) -> BaseModel | None:
        """Validate that access credentials contain real values.

        Args:
            access (BaseModel): Parsed access configuration.

        Returns:
            BaseModel | None: The validated access object.

        Raises:
            ValueError: If an access field is empty or contains a placeholder.
        """
        if access is None:
            return access

        for field, value in access.model_dump().items():
            if not isinstance(value, str):
                continue
            if not value.strip():
                raise ValueError(f"Access field '{field}' is empty")
            if any(marker in value for marker in ("YOUR-SECRET", "COMMIT")):
                raise ValueError(
                    f"Access field '{field}' still contains the placeholder '{value}'!"
                )
        return access


# ----------------------------------
# Per-source schemas - ENERGY
# ----------------------------------
class AdmeConfig(PathValidation, BaseModel):
    """Configuration schema for the ADME energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
    """

    source: Literal["adme"] = "adme"
    paths: Paths


class AemoConfig(PathValidation, AccessValidation, BaseModel):
    """Configuration schema for the AEMO energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
        access (AccessAPI): Access pydantic model for access settings.
    """

    source: Literal["aemo"] = "aemo"
    paths: Paths
    access: AccessAPI


class AesoConfig(PathValidation, AccessValidation, BaseModel):
    """Configuration schema for the AESO energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
        access (AccessAPI): Access pydantic model for access settings.
    """

    source: Literal["aeso"] = "aeso"
    paths: Paths
    access: AccessAPI


class CenConfig(PathValidation, AccessValidation, BaseModel):
    """Configuration schema for the CEN energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
        access (AccessAPI): Access pydantic model for access settings.
    """

    source: Literal["cen"] = "cen"
    paths: Paths
    access: AccessAPI


class EatConfig(PathValidation, BaseModel):
    """Configuration schema for the EAT energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
    """

    source: Literal["eat"] = "eat"
    paths: Paths


class EiaConfig(PathValidation, AccessValidation, BaseModel):
    """Configuration schema for the EIA energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
        access (AccessAPI): Access pydantic model for access settings.
    """

    source: Literal["eia"] = "eia"
    paths: Paths
    access: AccessAPI


class EntsoeConfig(PathValidation, AccessValidation, BaseModel):
    """Configuration schema for the ENTSO-E energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
        access (AccessAPI): Access pydantic model for access settings.
    """

    source: Literal["entsoe"] = "entsoe"
    paths: Paths
    access: AccessAPI


class EpiasConfig(PathValidation, AccessValidation, BaseModel):
    """Configuration schema for the EPIAS energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
        access (AccessAccount): Access pydantic model for access settings.
    """

    source: Literal["epias"] = "epias"
    paths: Paths
    access: AccessAccount


class IesoConfig(PathValidation, BaseModel):
    """Configuration schema for the IESO energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
    """

    source: Literal["ieso"] = "ieso"
    paths: Paths


class OnsConfig(PathValidation, BaseModel):
    """Configuration schema for the ONS energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
    """

    source: Literal["ons"] = "ons"
    paths: Paths


class ReiConfig(PathValidation, BaseModel):
    """Configuration schema for the REI energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
    """

    source: Literal["rei"] = "rei"
    paths: Paths


# ----------------------------------
# Per-source schemas - WEATHER
# ----------------------------------
class Era5Config(PathValidation, AccessValidation, BaseModel):
    """Configuration schema for the ERA5 reanalysis data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
        access (AccessAPI): Access pydantic model for access settings.
    """

    source: Literal["era5"] = "era5"
    paths: Paths
    access: AccessAPI


class IconDreamGlobalConfig(PathValidation, BaseModel):
    """Configuration schema for the ICON-DREAM Global weather data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
    """

    source: Literal["icon_dream_global"] = "icon_dream_global"
    paths: Paths


class IconDreamEuConfig(PathValidation, BaseModel):
    """Configuration schema for the ICON-DREAM EU weather data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
    """

    source: Literal["icon_dream_eu"] = "icon_dream_eu"
    paths: Paths


class Barra2Config(PathValidation, BaseModel):
    """Configuration schema for the BARRA2 reanalysis weather data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
    """

    source: Literal["barra2"] = "barra2"
    paths: Paths


class RegridPaths(BaseModel):
    """Filesystem paths used by the HEALPix regridding pipeline.

    Attributes:
        raw_data_base_dir (Path): Shared root all sources' already-downloaded
            raw data lives under, e.g. "/lsdf/raw/weather/". Passed straight
            through, unmodified, to every GridRegridder -- each one resolves
            its own "<raw_data_base_dir>/<raw_folder>/<temporal_res_folder>/"
            directory via rbc.weather.utils.raw_data_dir(), the same shared
            convention every WeatherDownloader itself writes into (raw_folder
            and temporal_res_folder come from that source's own MODEL_CONFIG
            in its mappings.py). No source needs a year subdirectory -- year
            is already embedded in each raw filename.
        weights_cache_dir (Path): Where grid-doctor's ESMF weight files are cached.
        dst_data_base_dir (Path): Shared root the regridded HEALPix output
            lives under. Per the weather Zarr contract, each
            (model_name, time_res, level) combination gets its own
            independent Zarr store at
            "<dst_data_base_dir>/<model_name>/<time_res>/level_<N>.zarr" --
            not one shared store with internal groups.
    """

    raw_data_base_dir: Path
    weights_cache_dir: Path
    dst_data_base_dir: Path


class RegridHealpixConfig(BaseModel):
    """Configuration schema for the HEALPix regridding pipeline.

    Deliberately skips `PathValidation`: every `*_raw_dir` must already contain
    data from that source's own downloader, so auto-creating a missing one
    (`PathValidation`'s behavior for every other schema's `paths`) would mask
    a real error instead of failing fast — `GridRegridder.__init__` already
    raises `FileNotFoundError` for a missing raw_dir; `weights_cache_dir` and
    `dst_data_base_dir` are created on demand by the code that writes to them.

    Attributes:
        source (Literal): Name of the data source.
        paths (RegridPaths): Paths pydantic model for paths.
        healpix_min_level (int): Shared coarsest HEALPix level across sources.
        healpix_max_level (dict[str, int]): Finest HEALPix level per source.
        variables (dict[str, list[str]] | None): Per-source variable override;
            None uses each regridder's own default.
    """

    source: Literal["regrid_healpix"] = "regrid_healpix"
    paths: RegridPaths
    healpix_min_level: int
    healpix_max_level: dict[str, int]
    variables: dict[str, list[str]] | None = None


# ----------------------------------
# Schema registry
# ----------------------------------
SCHEMA_REGISTRY: dict[str, Type[BaseModel]] = {
    "adme": AdmeConfig,
    "aemo": AemoConfig,
    "aeso": AesoConfig,
    "cen": CenConfig,
    "eat": EatConfig,
    "eia": EiaConfig,
    "entsoe": EntsoeConfig,
    "epias": EpiasConfig,
    "ieso": IesoConfig,
    "ons": OnsConfig,
    "rei": ReiConfig,
    "barra2": Barra2Config,
    "era5": Era5Config,
    "icon_dream_eu": IconDreamEuConfig,
    "icon_dream_global": IconDreamGlobalConfig,
    "regrid_healpix": RegridHealpixConfig,
}
