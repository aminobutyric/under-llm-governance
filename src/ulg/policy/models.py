# SPDX-License-Identifier: MPL-2.0

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DecisionKind(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action_id: UUID
    kind: DecisionKind
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
