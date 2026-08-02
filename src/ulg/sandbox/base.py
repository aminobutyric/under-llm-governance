# SPDX-License-Identifier: MPL-2.0

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class SandboxResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    recipe_name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    exit_code: int
    timed_out: bool
    output_bytes: int = Field(ge=0)
    output_truncated: bool


class SandboxRunner(Protocol):
    def run(self, *, recipe_name: str, workspace: Path) -> SandboxResult: ...
