# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
DecisionName = Literal["allow", "ask", "deny"]


def _toml_string_array(value: object) -> object:
    """Convert only TOML's native array representation to an immutable tuple."""

    if isinstance(value, list):
        return tuple(value)
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ModelSettings(StrictModel):
    provider: Literal["ollama"]
    name: str = Field(
        min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._/-]+(?::[A-Za-z0-9._-]+)?$"
    )
    endpoint: str
    request_timeout_seconds: PositiveInt
    max_response_bytes: PositiveInt

    @field_validator("name")
    @classmethod
    def reject_cloud_model_names(cls, value: str) -> str:
        if "cloud" in value.casefold():
            raise ValueError("MVP model must be local, not an Ollama cloud model")
        return value

    @field_validator("endpoint")
    @classmethod
    def require_loopback_http(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Ollama endpoint must use a numeric loopback HTTP origin")
        try:
            _ = parsed.port
        except ValueError as error:
            raise ValueError("Ollama endpoint has an invalid port") from error
        return value


class TaskSettings(StrictModel):
    max_turns: PositiveInt
    max_tool_calls: PositiveInt
    max_repeated_actions: PositiveInt
    max_model_failures: PositiveInt
    max_duration_seconds: PositiveInt
    max_context_bytes: PositiveInt


class WorkspaceSettings(StrictModel):
    mode: Literal["disposable_generations"]
    max_bytes: PositiveInt
    max_files: PositiveInt
    max_generations: PositiveInt
    max_manifest_bytes: PositiveInt
    retain_after_finish: bool
    respect_gitignore: bool
    deny_symlinks: bool
    deny_special_files: bool
    deny_cross_mounts: bool
    exclude: tuple[str, ...]

    _normalize_exclude = field_validator("exclude", mode="before")(_toml_string_array)

    @model_validator(mode="after")
    def enforce_workspace_invariants(self) -> WorkspaceSettings:
        if not self.deny_symlinks or not self.deny_special_files:
            raise ValueError("symlinks and special files must remain denied")
        if self.retain_after_finish:
            raise ValueError("workspace retention is not supported by the MVP")
        return self


class ListFilesTool(StrictModel):
    decision: DecisionName
    max_entries: PositiveInt
    max_depth: PositiveInt
    max_output_bytes: PositiveInt


class ReadFileTool(StrictModel):
    decision: DecisionName
    max_bytes: PositiveInt


class SearchTextTool(StrictModel):
    decision: DecisionName
    max_matches: PositiveInt
    max_output_bytes: PositiveInt


class ApplyPatchTool(StrictModel):
    decision: DecisionName
    max_patch_bytes: PositiveInt
    max_changed_files: PositiveInt
    ask_above_changed_files: NonNegativeInt
    ask_on_delete: bool


class ShowDiffTool(StrictModel):
    decision: DecisionName
    max_output_bytes: PositiveInt


class RunTaskTool(StrictModel):
    decision: DecisionName
    allowed_recipes: tuple[str, ...]
    grant_max_uses: PositiveInt
    grant_ttl_seconds: PositiveInt

    _normalize_allowed_recipes = field_validator("allowed_recipes", mode="before")(
        _toml_string_array
    )


class DeniedTool(StrictModel):
    decision: Literal["deny"]


class ToolsSettings(StrictModel):
    list_files: ListFilesTool
    read_file: ReadFileTool
    search_text: SearchTextTool
    apply_patch: ApplyPatchTool
    show_diff: ShowDiffTool
    run_task: RunTaskTool
    arbitrary_exec: DeniedTool
    network: DeniedTool
    install_dependencies: DeniedTool
    git_push: DeniedTool


class SandboxSettings(StrictModel):
    backend: Literal["rootless_docker"]
    network: Literal["none"]
    read_only_root: Literal[True]
    drop_capabilities: Literal["all"]
    no_new_privileges: Literal[True]
    memory_bytes: PositiveInt
    cpus: Annotated[float, Field(gt=0)]
    pids: PositiveInt
    wall_time_seconds: PositiveInt
    max_combined_output_bytes: PositiveInt
    tmpfs_bytes: PositiveInt


class RecipeSettings(StrictModel):
    argv: tuple[str, ...] = Field(min_length=1)

    _normalize_argv = field_validator("argv", mode="before")(_toml_string_array)

    @field_validator("argv")
    @classmethod
    def reject_empty_arguments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not argument or "\x00" in argument for argument in value):
            raise ValueError("recipe arguments must be non-empty and NUL-free")
        return value


class ExportSettings(StrictModel):
    format: Literal["unified_diff"]
    modify_original: Literal[False]
    destroy_workspace_after_export: Literal[True]


class AuditSettings(StrictModel):
    format: Literal["jsonl"]
    append_only: Literal[True]
    redact_before_serialize: Literal[True]
    accept_raw_payloads: Literal[False]
    include_file_contents: Literal[False]
    include_environment: Literal[False]
    max_event_bytes: PositiveInt
    max_preview_bytes: NonNegativeInt


class AppConfig(StrictModel):
    version: Literal[1]
    model: ModelSettings
    task: TaskSettings
    workspace: WorkspaceSettings
    tools: ToolsSettings
    sandbox: SandboxSettings
    recipes: dict[str, RecipeSettings]
    export: ExportSettings
    audit: AuditSettings

    @model_validator(mode="after")
    def recipes_must_match_allowlist(self) -> AppConfig:
        configured = set(self.recipes)
        allowed = set(self.tools.run_task.allowed_recipes)
        if configured != allowed:
            raise ValueError("configured recipes must exactly match allowed_recipes")
        if self.model.request_timeout_seconds > self.task.max_duration_seconds:
            raise ValueError("model request timeout cannot exceed task duration")
        return self
