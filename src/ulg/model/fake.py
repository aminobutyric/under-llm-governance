# SPDX-License-Identifier: MPL-2.0

from collections import deque
from collections.abc import Iterable
from uuid import UUID

from ulg.actions import Action


class FakeModel:
    """Deterministic adapter for controller and policy contract tests."""

    def __init__(self, actions: Iterable[Action]) -> None:
        self._actions = deque(actions)

    def propose(self, *, task_id: UUID, prompt: str) -> Action:
        del prompt
        if not self._actions:
            raise RuntimeError("fake model has no actions remaining")
        action = self._actions.popleft()
        if action.task_id != task_id:
            raise ValueError("model action task_id does not match the active task")
        return action
