# SPDX-License-Identifier: MPL-2.0

from typing import Protocol
from uuid import UUID

from ulg.actions import Action


class ModelAdapter(Protocol):
    def propose(self, *, task_id: UUID, prompt: str) -> Action: ...
