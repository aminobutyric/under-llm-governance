# SPDX-License-Identifier: MPL-2.0

from collections.abc import Sequence
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ulg.actions import Action


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    role: Literal["user", "assistant", "tool"]
    content: str = Field(max_length=8_388_608)


class ModelAdapter(Protocol):
    def propose(self, *, task_id: UUID, messages: Sequence[ChatMessage]) -> Action: ...
