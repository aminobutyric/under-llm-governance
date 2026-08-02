# SPDX-License-Identifier: MPL-2.0

from collections import deque
from collections.abc import Iterable, Sequence
from uuid import UUID

from ulg.actions import Action
from ulg.model.base import ChatMessage


class FakeModel:
    """Deterministic adapter for controller and policy contract tests."""

    def __init__(self, actions: Iterable[Action]) -> None:
        self._actions = deque(actions)

    def propose(self, *, task_id: UUID, messages: Sequence[ChatMessage]) -> Action:
        del messages
        if not self._actions:
            raise RuntimeError("fake model has no actions remaining")
        action = self._actions.popleft()
        if action.task_id != task_id:
            raise ValueError("model action task_id does not match the active task")
        return action
