# SPDX-License-Identifier: MPL-2.0

from pathlib import Path

from ulg.config import load_config


def test_example_policy_is_strictly_valid() -> None:
    config = load_config(Path("config/policy.example.toml"))

    assert config.version == 1
    assert config.model.provider == "ollama"
    assert config.sandbox.network == "none"
    assert config.export.modify_original is False
