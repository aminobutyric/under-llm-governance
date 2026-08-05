# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResultBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    action_id: UUID
    ok: bool
    truncated: bool = False
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")


class FileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: str
    kind: Literal["file", "directory"]
    size: int = Field(ge=0)


class ListFilesResult(ResultBase):
    type: Literal["list_files_result"] = "list_files_result"
    entries: tuple[FileEntry, ...] = ()


class ReadFileResult(ResultBase):
    type: Literal["read_file_result"] = "read_file_result"
    path: str
    content: str = ""
    bytes_read: int = Field(ge=0)


class SearchMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: str
    line_number: int = Field(gt=0)
    line: str = Field(max_length=1_000)


class SearchTextResult(ResultBase):
    type: Literal["search_text_result"] = "search_text_result"
    matches: tuple[SearchMatch, ...] = ()


class ApplyPatchResult(ResultBase):
    type: Literal["apply_patch_result"] = "apply_patch_result"
    generation: int = Field(ge=0)
    changed_files: tuple[str, ...] = ()
    deleted_files: tuple[str, ...] = ()
    parent_tree_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    tree_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    correction: str | None = Field(default=None, max_length=500)


class ShowDiffResult(ResultBase):
    type: Literal["show_diff_result"] = "show_diff_result"
    diff: str = ""
    bytes_returned: int = Field(ge=0)


class RunTaskResult(ResultBase):
    type: Literal["run_task_result"] = "run_task_result"
    recipe_name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    recipe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sandbox_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    exit_code: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    duration_ms: int = Field(ge=0)
    output: str = Field(default="", max_length=1_048_576)
    output_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_execution_outcome(self) -> RunTaskResult:
        stored_bytes = len(self.output.encode("utf-8"))
        if stored_bytes > self.output_bytes:
            raise ValueError("stored output cannot exceed observed output bytes")
        if not self.truncated and stored_bytes != self.output_bytes:
            raise ValueError("untruncated output byte count must match output")
        if self.timed_out and self.cancelled:
            raise ValueError("sandbox result cannot be both timed out and cancelled")
        if self.ok and (
            self.exit_code != 0
            or self.timed_out
            or self.cancelled
            or self.error_code is not None
        ):
            raise ValueError("successful sandbox result has a failing outcome")
        if not self.ok and not (
            self.exit_code not in {None, 0}
            or self.timed_out
            or self.cancelled
            or self.error_code is not None
        ):
            raise ValueError("failed sandbox result must describe its failure")
        return self


ToolResult = Annotated[
    ListFilesResult
    | ReadFileResult
    | SearchTextResult
    | ApplyPatchResult
    | ShowDiffResult
    | RunTaskResult,
    Field(discriminator="type"),
]
