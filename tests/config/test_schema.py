# tests/config/test_schema.py
from pathlib import Path

import pytest
from pydantic import ValidationError

from rbc.config.schema import SCHEMA_REGISTRY


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
