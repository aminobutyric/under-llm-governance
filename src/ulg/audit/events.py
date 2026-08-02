# SPDX-License-Identifier: MPL-2.0

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ulg.policy import DecisionKind


class AuditEvent(BaseModel):
    """Audit-safe metadata. Raw prompts and tool payloads are intentionally absent."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    event_type: Literal["action_decided"] = "action_decided"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    task_id: UUID
    action_id: UUID
    action_type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    decision: DecisionKind
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    executed: bool = False
