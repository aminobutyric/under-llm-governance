# SPDX-License-Identifier: MPL-2.0

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ulg.actions import Action


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action_id: UUID
    ok: bool
    summary: str = Field(max_length=4_000)
    truncated: bool = False


class ToolRunner(Protocol):
    def execute(self, action: Action) -> ToolResult: ...
