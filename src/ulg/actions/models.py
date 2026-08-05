# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


def _validate_workspace_path(value: str) -> str:
    if value.startswith("/") or "\x00" in value or ".." in PurePosixPath(value).parts:
        raise ValueError("path must be a contained, non-NUL relative path")
    return value


class ActionBase(BaseModel):
    """Fields shared by every untrusted model-proposed action."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    action_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    rationale: str = Field(min_length=1, max_length=500)


class ListFilesAction(ActionBase):
    type: Literal["list_files"] = "list_files"
    path: str = Field(default=".", min_length=1, max_length=4096)
    recursive: bool = True

    _require_relative_path = field_validator("path")(_validate_workspace_path)


class ReadFileAction(ActionBase):
    type: Literal["read_file"] = "read_file"
    path: str = Field(min_length=1, max_length=4096)

    _require_relative_path = field_validator("path")(_validate_workspace_path)


class SearchTextAction(ActionBase):
    type: Literal["search_text"] = "search_text"
    path: str = Field(default=".", min_length=1, max_length=4096)
    query: str = Field(min_length=1, max_length=1_000)
    case_sensitive: bool = True

    _require_relative_path = field_validator("path")(_validate_workspace_path)


class ApplyPatchAction(ActionBase):
    type: Literal["apply_patch"] = "apply_patch"
    patch: str = Field(min_length=1, max_length=1_048_576)


class ShowDiffAction(ActionBase):
    type: Literal["show_diff"] = "show_diff"


class RunTaskAction(ActionBase):
    type: Literal["run_task"] = "run_task"
    recipe_name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_-]{0,63}$",
    )


class CompleteAction(ActionBase):
    type: Literal["complete"] = "complete"
    summary: str = Field(min_length=1, max_length=4_000)


Action = Annotated[
    ListFilesAction
    | ReadFileAction
    | SearchTextAction
    | ApplyPatchAction
    | ShowDiffAction
    | RunTaskAction
    | CompleteAction,
    Field(discriminator="type"),
]
_ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)


def parse_action(payload: object) -> Action:
    """Validate an untrusted action payload and reject unknown fields/types."""

    return _ACTION_ADAPTER.validate_python(payload)


def parse_action_json(payload: str | bytes) -> Action:
    """Validate JSON from a model while retaining strict JSON-aware types."""

    return _ACTION_ADAPTER.validate_json(payload)


def action_json_schema() -> dict[str, object]:
    return _ACTION_ADAPTER.json_schema()


def ollama_action_json_schema() -> dict[str, object]:
    """Return a grammar-friendly hint; strict validation still uses ``Action``."""

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "const": 1},
            "task_id": {"type": "string"},
            "rationale": {"type": "string", "minLength": 1, "maxLength": 500},
            "type": {
                "type": "string",
                "enum": [
                    "list_files",
                    "read_file",
                    "search_text",
                    "apply_patch",
                    "show_diff",
                    "complete",
                ],
            },
            "path": {"type": "string", "minLength": 1, "maxLength": 4096},
            "recursive": {"type": "boolean"},
            "query": {"type": "string", "minLength": 1, "maxLength": 1000},
            "case_sensitive": {"type": "boolean"},
            "summary": {"type": "string", "minLength": 1, "maxLength": 4000},
            "patch": {"type": "string", "minLength": 1, "maxLength": 1048576},
        },
        "required": ["schema_version", "task_id", "rationale", "type"],
    }
