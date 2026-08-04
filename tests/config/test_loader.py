# tests/config/test_loader.py
import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

import rbc.config.loader as loader
from rbc.config.schema import SCHEMA_REGISTRY


def _override_value(value):
    """Produce a schema-valid override, distinct from the original value.

    Args:
        value: Original config value.

    Returns:
        A different value of a type the same field would still accept.
    """
    if isinstance(value, int):
        return value + 1
    return "override"


# ----------------------------------
# Tests
# ----------------------------------
class TestLoadConfig:
    """Tests for the "load_config" function."""

    @pytest.mark.parametrize("source", list(SCHEMA_REGISTRY.keys()))
    def test_load_config(self, tmp_configs_dir: Path, source: str) -> None:
        """Happy path for "load_config" function.

        Check that "load_config" loads a YAML config for a source correctly.

        Args:
            tmp_configs_dir (Path): Path to the temporary config directory.
            source (str): Name of the data source (input to "load_config").
        """
        received_cfg_obj = loader.load_config(
            source=source, configs_dir=tmp_configs_dir
        )
        assert received_cfg_obj.source == source

    @pytest.mark.parametrize("source", list(SCHEMA_REGISTRY.keys()))
    def test_load_config_with_overrides(
        self, tmp_configs_dir: Path, source_configs: dict, source: str
    ) -> None:
        """Happy path for "load_config" function.

        Check that "load_config" loads a YAML config for a source correctly
        with overrides.

        Args:
            tmp_configs_dir (Path): Path to the temporary config directory.
            source_configs (dict): Dictionary of source configurations.
            source (str): Name of the data source (input to "load_config").
        """
        assert source in source_configs, f"Missing test cfg for source '{source}'"
        cfg_dict = source_configs[source]
        overrides = {
            k: (
                {sub_k: _override_value(sub_v) for sub_k, sub_v in v.items()}
                if isinstance(v, dict)
                else _override_value(v)
            )
            for k, v in cfg_dict.items()
        }

        with patch("rbc.config.schema.Path.mkdir"):
            received_cfg_obj = loader.load_config(
                source=source, configs_dir=tmp_configs_dir, overrides=overrides
            )

        received_cfg_dict = received_cfg_obj.model_dump(mode="json")

        for k, expected_v in overrides.items():
            if isinstance(expected_v, dict):
                for sub_k, sub_v in expected_v.items():
                    assert received_cfg_dict[k][sub_k] == sub_v
            else:
                assert received_cfg_dict[k] == expected_v

    def test_load_config_missing_file(self, tmp_configs_dir: Path) -> None:
        """Failure path for "load_config" function when YAML is missing.

        Args:
            tmp_configs_dir (Path): Path to the temporary config directory.
        """
        fake_cfg_path = Path(tmp_configs_dir, "fake.yaml")
        fake_cfg_path.unlink(missing_ok=True)

        with pytest.raises(ValueError, match="Source 'fake' is missing"):
            loader.load_config(source="fake", configs_dir=fake_cfg_path)

    def test_load_config_unknown_source(self, tmp_configs_dir: Path) -> None:
        """Failure path for "load_config" function when data source is not in registry.

        Args:
            tmp_configs_dir (Path): Path to the temporary config directory.
        """
        unknown_cfg_path = Path(tmp_configs_dir, "unknown.yaml")
        unknown_cfg_path.write_text("")

        with pytest.raises(ValueError, match="Unknown source"):
            loader.load_config(source="unknown", configs_dir=tmp_configs_dir)


# ----------------------------------
# Tests - Helper functions
# ----------------------------------
class TestUpdateConfig:
    """Tests for the "update_config" helper function."""

    @pytest.mark.parametrize(
        "input_cfg, updates, expected_cfg",
        [
            ({"a": 1}, {"a": 2}, {"a": 2}),
            ({"a": 1}, {"a": "none"}, {"a": None}),
            ({"a": {"b": 1}}, {"a": {"b": 2}}, {"a": {"b": 2}}),
        ],
        ids=["standard_update", "adapt_none", "nested_update"],
    )
    def test_update_config(
        self, input_cfg: dict, updates: dict, expected_cfg: dict
    ) -> None:
        """Happy path for "update_config" function.

        Args:
            input_cfg (dict): Dictionary of exemplary input config.
            updates (dict): Dictionary of updates.
            expected_cfg (dict): Dictionary of expected updated config.
        """
        assert expected_cfg == loader.update_config(input_cfg, updates)


class TestParseKeyValuePairs:
    """Tests for the "parse_key_value_pairs" helper function."""

    @pytest.mark.parametrize(
        "inputs, expected_outputs",
        [
            ([], {}),
            (["a=1"], {"a": "1"}),
            (["a.b=x"], {"a": {"b": "x"}}),
            (["a.b=x", "c.d=y"], {"a": {"b": "x"}, "c": {"d": "y"}}),
            (["a.b.c=deep"], {"a": {"b": {"c": "deep"}}}),
        ],
        ids=[
            "none",
            "a_pair",
            "a_nested_pair",
            "two_nested_pairs",
            "a_deep_nested_pair",
        ],
    )
    def test_parse_key_value_pairs(self, inputs: list, expected_outputs: dict) -> None:
        """Happy path for "parse_key_value_pairs" function.

        Args:
            inputs (list): List of pairs to parse.
            expected_outputs (dict): Dictionary of expected outputs pairs.
        """
        returned_outputs = loader.parse_key_value_pairs(inputs)
        assert isinstance(returned_outputs, dict)
        assert expected_outputs == returned_outputs

    @pytest.mark.parametrize(
        "invalid_input, msg",
        [
            (["no_equals_sign"], "Invalid format"),
            (["a=1", "a.b=2"], "Conflict at 'a': cannot overwrite key"),
            (["a.b=2", "a=1"], "Conflict at 'a': cannot overwrite a"),
        ],
        ids=["no_equal", "variable_int_to_dict", "variable_dict_to_int"],
    )
    def test_parse_key_value_pairs_invalid_input(
        self, invalid_input: list, msg: str
    ) -> None:
        """Failure path for "parse_key_value_pairs" function when the input is invalid.

        Inputs are invalid if either the format isn't correct (no "=") or there is a
        conflict because key combinations were provided that can't overwrite one another.

        Args:
            invalid_input (list): List of invalid pairs to parse.
            msg (str): Message describing the error.
        """
        with pytest.raises(argparse.ArgumentTypeError, match=msg):
            loader.parse_key_value_pairs(invalid_input)
