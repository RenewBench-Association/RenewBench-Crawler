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


class IesoConfig(BaseModel):
    """Configuration schema for the IESO energy data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
    """

    source: Literal["ieso"] = "ieso"
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


class IconDreamGlobalConfig(BaseModel):
    """Configuration schema for the ICON-DREAM Global weather data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
    """

    source: Literal["icon_dream_global"] = "icon_dream_global"
    paths: Paths


class IconDreamEuConfig(BaseModel):
    """Configuration schema for the ICON-DREAM EU weather data source.

    Attributes:
        source (Literal): Name of the data source.
        paths (Paths): Paths pydantic model for paths.
    """

    source: Literal["icon_dream_eu"] = "icon_dream_eu"
    paths: Paths


# ----------------------------------
# Schema registry
# ----------------------------------
SCHEMA_REGISTRY: dict[str, Type[BaseModel]] = {
    "eia": EiaConfig,
    "entsoe": EntsoeConfig,
    "epias": EpiasConfig,
    "ieso": IesoConfig,
    "era5": Era5Config,
    "icon_dream_global": IconDreamGlobalConfig,
    "icon_dream_eu": IconDreamEuConfig,
}
