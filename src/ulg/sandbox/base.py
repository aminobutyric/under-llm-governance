# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SandboxResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    recipe_name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    recipe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sandbox_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    ok: bool
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    exit_code: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    duration_ms: int = Field(ge=0)
    output: str = Field(default="", max_length=1_048_576)
    output_bytes: int = Field(ge=0)
    output_truncated: bool = False

    @model_validator(mode="after")
    def validate_outcome(self) -> SandboxResult:
        stored_bytes = len(self.output.encode("utf-8"))
        if stored_bytes > self.output_bytes:
            raise ValueError("stored output cannot exceed observed output bytes")
        if not self.output_truncated and stored_bytes != self.output_bytes:
            raise ValueError("untruncated output byte count must match output")
        if self.timed_out and self.cancelled:
            raise ValueError("sandbox cannot be both timed out and cancelled")
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


class SandboxRunner(Protocol):
    def run(self, *, recipe_name: str, workspace: Path) -> SandboxResult: ...
