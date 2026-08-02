# SPDX-License-Identifier: MPL-2.0

from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: UUID
    root: Path
    generation: int = Field(ge=0)


class WorkspaceManager(Protocol):
    def create(self, *, source: Path, task_id: UUID) -> WorkspaceRef: ...

    def discard(self, workspace: WorkspaceRef) -> None: ...
