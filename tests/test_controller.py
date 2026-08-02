# SPDX-License-Identifier: MPL-2.0

from uuid import uuid4

from ulg.actions import ListFilesAction
from ulg.audit import MemoryAuditSink
from ulg.controller import Controller
from ulg.model import FakeModel
from ulg.policy import BaselinePolicy, DecisionKind


def test_dry_run_crosses_contracts_without_executing_tool() -> None:
    task_id = uuid4()
    action = ListFilesAction(
        task_id=task_id,
        rationale="inspect the workspace",
        path=".",
    )
    audit = MemoryAuditSink()
    controller = Controller(
        model=FakeModel([action]),
        policy=BaselinePolicy(),
        audit=audit,
    )

    result = controller.dry_run_once(task_id=task_id, prompt="inspect")

    assert result.decision is DecisionKind.ALLOW
    assert result.executed is False
    assert len(audit.events) == 1
    assert audit.events[0].executed is False
