# tests/config/test_loader.py
import argparse
from pathlib import Path

import pytest

import rbc.config.loader as loader
from rbc.config.schema import SCHEMA_REGISTRY


# ----------------------------------
# Tests
# ----------------------------------
@pytest.mark.parametrize("source", list(SCHEMA_REGISTRY.keys()))
def test_load_config(tmp_configs_dir: Path, source: str) -> None:
    """Happy path for "load_config" function.

    Check that "load_config" loads a YAML config for a source correctly.

    Args:
        tmp_configs_dir (Path): Path to the temporary config directory.
        source (str): Name of the data source (input to "load_config").
    """
    received_cfg_obj = loader.load_config(source=source, configs_dir=tmp_configs_dir)
    assert received_cfg_obj.source == source


@pytest.mark.parametrize("source", list(SCHEMA_REGISTRY.keys()))
def test_load_config_with_overrides(
    tmp_configs_dir: Path, source_configs: dict, source: str
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
        k: ({sub_k: "override" for sub_k in v} if isinstance(v, dict) else "override")
        for k, v in cfg_dict.items()
    }

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


def test_load_config_missing_file(tmp_configs_dir: Path) -> None:
    """Failure path for "load_config" function when YAML is missing.

    Args:
        tmp_configs_dir (Path): Path to the temporary config directory.
    """
    fake_cfg_path = Path(tmp_configs_dir, "fake.yaml")
    fake_cfg_path.unlink(missing_ok=True)

    with pytest.raises(ValueError, match="missing"):
        loader.load_config(source="fake", configs_dir=tmp_configs_dir)


def test_load_config_unknown_source(tmp_configs_dir: Path) -> None:
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
@pytest.mark.parametrize(
    "inputs, expected_outputs",
    [
        ([], {}),
        (["a=1"], {"a": "1"}),
        (["a.b=x"], {"a": {"b": "x"}}),
        (["a.b=x", "c.d=y"], {"a": {"b": "x"}, "c": {"d": "y"}}),
        (["a.b.c=deep"], {"a": {"b": {"c": "deep"}}}),
    ],
)
def test_parse_key_value_pairs(inputs: list, expected_outputs: dict) -> None:
    """Happy path for "parse_key_value_pairs" function.

    Args:
        inputs (list): List of pairs to parse.
        expected_outputs (dict): Dictionary of expected outputs pairs.
    """
    returned_outputs = loader.parse_key_value_pairs(inputs)
    assert type(returned_outputs) is dict
    assert expected_outputs == returned_outputs


@pytest.mark.parametrize(
    "invalid_input, msg",
    [
        (["no_equals_sign"], "Invalid format"),
        (
            ["a=1", "a.b=2"],
            "Conflict at 'a': cannot overwrite key",
        ),  # Scalar turned dict
        (["a.b=2", "a=1"], "Conflict at 'a': cannot overwrite a"),  # Dict turned scalar
    ],
)
def test_parse_key_value_pairs_invalid_input(invalid_input: list, msg: str) -> None:
    """Failure path for "parse_key_value_pairs" function when the input is invalid.

    Inputs are invalid if either the format isn't correct (no "=") or there is a
    conflict because key combinations were provided that can't overwrite one another.

    Args:
        invalid_input (list): List of invalid pairs to parse.
        msg (str): Message describing the error.
    """
    with pytest.raises(argparse.ArgumentTypeError, match=msg):
        loader.parse_key_value_pairs(invalid_input)
