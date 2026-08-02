# SPDX-License-Identifier: MPL-2.0

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


ToolResult = Annotated[
    ListFilesResult
    | ReadFileResult
    | SearchTextResult
    | ApplyPatchResult
    | ShowDiffResult,
    Field(discriminator="type"),
]
