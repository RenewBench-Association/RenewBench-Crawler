# tests/config/test_schema.py
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from rbc.config.schema import (
    SCHEMA_REGISTRY,
    AccessAPI,
    AccessValidation,
    Paths,
    PathValidation,
)


# -------------------------------------------------
# Tests - Validator schemas
# -------------------------------------------------
class TestPathValidation:
    """Tests for the "PathValidation" validator class."""

    def test_check_paths(self) -> None:
        """Happy path for "PathValidation" class."""
        with patch("rbc.config.schema.Path.mkdir") as mock_mkdir:
            obj = Paths(dst_dir_raw="/tmp/str")
            config = PathValidation.check_paths(obj)

            assert config.dst_dir_raw == Path("/tmp/str")
            assert mock_mkdir.call_count == 1

    @pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
    def test_check_paths_ignores_non_string(self) -> None:
        """Happy path for "PathValidation" class, where non-str/path values are ignored."""
        with patch("rbc.config.schema.Path.mkdir") as mock_mkdir:
            obj = Paths.model_construct(dst_dir_raw=42)
            PathValidation.check_paths(obj)

            assert mock_mkdir.call_count == 0  # skips int, does not run mkdir

    def test_check_paths_permission_error(self) -> None:
        """Failure path for "PathValidation" class, where permission/OS issues cause error."""
        with patch("rbc.config.schema.Path.mkdir") as mock_mkdir:
            mock_mkdir.side_effect = PermissionError("Permission denied")
            obj = Paths(dst_dir_raw="/root/secret")

            with pytest.raises(ValueError, match="not writable or cannot be created"):
                PathValidation.check_paths(obj)


class TestAccessValidation:
    """Tests for the "AccessValidation" validator class."""

    @pytest.mark.parametrize("access_input", ["real_api_key", 42])
    @pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
    def test_check_access_values(self, access_input: Any) -> None:
        """Happy path for "AccessValidation" class, with valid string or different type.

        Args:
            access_input (Any): Access input value to be validated.
        """
        obj = AccessAPI.model_construct(api_key=access_input)
        config = AccessValidation.check_access_values(obj)

        assert config is not None
        assert config.api_key == access_input

    def test_check_access_handles_none(self) -> None:
        """Happy path for "AccessValidation" class, if access is None."""
        assert AccessValidation.check_access_values(None) is None

    @pytest.mark.parametrize(
        "invalid_value, expected_error_msg",
        [
            ("   ", "is empty"),
            ("", "is empty"),
            ("YOUR-SECRET", "still contains the placeholder"),
            ("DO-NOT-COMMIT", "still contains the placeholder"),
        ],
        ids=["whitespace", "empty", "placeholder_secret", "placeholder_commit"],
    )
    def test_check_access_values_value_error(
        self, invalid_value: str, expected_error_msg: str
    ) -> None:
        """Failure path for "AccessValidation" when ValueError is raised."""
        obj = AccessAPI(api_key=invalid_value)

        with pytest.raises(ValueError, match=expected_error_msg):
            AccessValidation.check_access_values(obj)


# -------------------------------------------------
# Tests - Schema usage
# -------------------------------------------------
@pytest.mark.parametrize("source", list(SCHEMA_REGISTRY.keys()))
def test_config_validates(source: str, source_configs: dict) -> None:
    """Happy path for data source schemas.

    Check the config output is valid given a set of expected inputs.

    Args:
        source (str): Name of the data source.
        source_configs (dict): Dictionary of all source configurations.
    """
    schema = SCHEMA_REGISTRY[source]
    cfg_dict = source_configs[source]

    received_cfg_obj = schema.model_validate({"source": source, **cfg_dict})
    received_cfg_dict = received_cfg_obj.model_dump(mode="json")

    assert received_cfg_obj.source == source
    for k, exp_v in cfg_dict.items():
        if isinstance(exp_v, dict):
            for sub_k, sub_v in exp_v.items():
                received_v = received_cfg_dict[k][sub_k]
                if isinstance(sub_v, str) and ("/" in sub_v or "\\" in sub_v):
                    assert Path(received_v) == Path(sub_v)
                else:
                    assert received_v == sub_v
        else:
            assert received_cfg_dict[k] == exp_v


@pytest.mark.parametrize("source", list(SCHEMA_REGISTRY.keys()))
@pytest.mark.parametrize("bad", ["", "   ", "YOUR-SECRET", "COMMIT"])
def test_config_with_access_rejects_placeholders(
    source: str, source_configs: dict, bad: str
) -> None:
    """Failure path for data source schemas with "access" fields.

    Check that schemas with access requirements reject placeholders or empty
    values.

    Args:
        source (str): Name of the data source.
        source_configs (dict): Dictionary of all source configurations.
        bad (str): Possible bad access string (placeholder or empty).
    """
    schema = SCHEMA_REGISTRY[source]
    cfg_dict = source_configs[source]

    if not cfg_dict.get("access"):
        pytest.skip(f"Source '{source}' has no access block. Skipped.")

    bad_cfg_dict = {
        "source": source,
        **cfg_dict,
        "access": {k: bad for k in cfg_dict["access"].keys()},
    }

    with pytest.raises(ValidationError):
        schema.model_validate(bad_cfg_dict)
