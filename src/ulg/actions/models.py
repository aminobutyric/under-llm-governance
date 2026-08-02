# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


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

    @field_validator("path")
    @classmethod
    def require_relative_path(cls, value: str) -> str:
        if (
            value.startswith("/")
            or "\x00" in value
            or ".." in PurePosixPath(value).parts
        ):
            raise ValueError("path must be a contained, non-NUL relative path")
        return value


class CompleteAction(ActionBase):
    type: Literal["complete"] = "complete"
    summary: str = Field(min_length=1, max_length=4_000)


Action = Annotated[ListFilesAction | CompleteAction, Field(discriminator="type")]
_ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)


def parse_action(payload: object) -> Action:
    """Validate an untrusted action payload and reject unknown fields/types."""

    return _ACTION_ADAPTER.validate_python(payload)
