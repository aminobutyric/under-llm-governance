# SPDX-License-Identifier: MPL-2.0

from pathlib import Path

import pytest
from pydantic import ValidationError

from ulg.config import load_config
from ulg.config.models import WorkspaceSettings


def test_example_policy_is_strictly_valid() -> None:
    config = load_config(Path("config/policy.example.toml"))

    assert config.version == 1
    assert config.model.provider == "ollama"
    assert config.sandbox.network == "none"
    assert config.export.modify_original is False


def test_workspace_retention_cannot_be_enabled_before_it_is_supported() -> None:
    config = load_config(Path("config/policy.example.toml"))
    payload = {**config.workspace.model_dump(), "retain_after_finish": True}

    with pytest.raises(ValidationError, match="retention is not supported"):
        WorkspaceSettings.model_validate(payload)
