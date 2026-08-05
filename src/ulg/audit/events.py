# SPDX-License-Identifier: MPL-2.0

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ulg.policy import DecisionKind


class AuditEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    task_id: UUID


class TaskLifecycleEvent(AuditEventBase):
    event_type: Literal["task_started", "task_completed", "task_failed"]
    reason_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")


class ActionDecisionEvent(AuditEventBase):
    event_type: Literal["action_decided"] = "action_decided"
    action_id: UUID
    action_type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    decision: DecisionKind
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    executed: bool = False


class ToolFinishedEvent(AuditEventBase):
    event_type: Literal["tool_finished"] = "tool_finished"
    action_id: UUID
    action_type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    ok: bool
    truncated: bool
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")


class ModelFailureEvent(AuditEventBase):
    event_type: Literal["model_failed"] = "model_failed"
    error_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    retrying: bool


class WorkspaceGenerationEvent(AuditEventBase):
    event_type: Literal["workspace_generation_published"] = (
        "workspace_generation_published"
    )
    action_id: UUID
    generation: int = Field(gt=0)
    parent_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SandboxFinishedEvent(AuditEventBase):
    event_type: Literal["sandbox_finished"] = "sandbox_finished"
    action_id: UUID | None = None
    recipe_name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    recipe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sandbox_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    ok: bool
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    exit_code: int | None = None
    timed_out: bool
    cancelled: bool
    duration_ms: int = Field(ge=0)
    output_bytes: int = Field(ge=0)
    output_truncated: bool


class PatchExportedEvent(AuditEventBase):
    event_type: Literal["patch_exported"] = "patch_exported"
    generation: int = Field(gt=0)
    bytes_written: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recovered_after_failure: bool = False


class WorkspaceDiscardedEvent(AuditEventBase):
    event_type: Literal["workspace_discarded"] = "workspace_discarded"
    generation: int = Field(ge=0)
    reason_code: Literal["completed", "failed", "cancelled"]
    patch_exported: bool


AuditEvent = Annotated[
    TaskLifecycleEvent
    | ActionDecisionEvent
    | ToolFinishedEvent
    | ModelFailureEvent
    | WorkspaceGenerationEvent
    | SandboxFinishedEvent
    | PatchExportedEvent
    | WorkspaceDiscardedEvent,
    Field(discriminator="event_type"),
]
