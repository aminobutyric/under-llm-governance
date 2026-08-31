# SPDX-License-Identifier: MPL-2.0

from pathlib import Path

import pytest
from pydantic import ValidationError

from ulg.config import load_config
from ulg.config.models import AppConfig, WorkspaceSettings


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


def test_run_task_policy_must_remain_ask_and_have_unique_recipe_names() -> None:
    config = load_config(Path("config/policy.example.toml"))
    payload = config.model_dump()
    payload["tools"]["run_task"]["decision"] = "allow"

    with pytest.raises(ValidationError):
        AppConfig.model_validate(payload)

    duplicate_payload = config.model_dump()
    allowed = list(duplicate_payload["tools"]["run_task"]["allowed_recipes"])
    duplicate_payload["tools"]["run_task"]["allowed_recipes"] = [*allowed, "test"]
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        AppConfig.model_validate(duplicate_payload)

    excessive_grant = config.model_dump()
    excessive_grant["tools"]["run_task"]["grant_max_uses"] = 1_001
    with pytest.raises(ValidationError):
        AppConfig.model_validate(excessive_grant)

    excessive_ttl = config.model_dump()
    excessive_ttl["tools"]["run_task"]["grant_ttl_seconds"] = 86_401
    with pytest.raises(ValidationError):
        AppConfig.model_validate(excessive_ttl)

    excessive_patch_ttl = config.model_dump()
    excessive_patch_ttl["tools"]["apply_patch"]["grant_ttl_seconds"] = 86_401
    with pytest.raises(ValidationError):
        AppConfig.model_validate(excessive_patch_ttl)


def test_sandbox_image_and_resource_limits_are_strict() -> None:
    config = load_config(Path("config/policy.example.toml"))

    mutable_digest = config.model_dump()
    mutable_digest["sandbox"]["image_digest"] = "latest"
    with pytest.raises(ValidationError):
        AppConfig.model_validate(mutable_digest)

    excessive_output = config.model_dump()
    excessive_output["sandbox"]["max_combined_output_bytes"] = 1_048_577
    with pytest.raises(ValidationError):
        AppConfig.model_validate(excessive_output)

    oversized_tmpfs = config.model_dump()
    oversized_tmpfs["sandbox"]["workspace_tmpfs_bytes"] = 500_000_000
    with pytest.raises(ValidationError, match="tmpfs limits must fit"):
        AppConfig.model_validate(oversized_tmpfs)
