# SPDX-License-Identifier: MPL-2.0

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ulg.actions import Action, ApplyPatchAction, CompleteAction, ListFilesAction
from ulg.audit import MemoryAuditSink
from ulg.config import load_config
from ulg.controller import Controller, ControllerLimitError, ReadOnlyController
from ulg.model import ChatMessage, FakeModel, ModelProtocolError
from ulg.policy import BaselinePolicy, DecisionKind
from ulg.tools import ListFilesResult


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


class _StubTools:
    def execute(self, action: object) -> ListFilesResult:
        assert isinstance(action, ListFilesAction)
        return ListFilesResult(action_id=action.action_id, ok=True)


class _RecoveringModel:
    def __init__(self) -> None:
        self.calls = 0

    def propose(self, *, task_id: UUID, messages: Sequence[ChatMessage]) -> Action:
        del messages
        self.calls += 1
        if self.calls == 1:
            raise ModelProtocolError("invalid_action", "invalid")
        return CompleteAction(
            task_id=task_id,
            rationale="corrected",
            summary="done",
        )


class _PatchCorrectionModel:
    def __init__(self) -> None:
        self.calls = 0

    def propose(self, *, task_id: UUID, messages: Sequence[ChatMessage]) -> Action:
        self.calls += 1
        if self.calls == 1:
            return ApplyPatchAction(
                task_id=task_id,
                rationale="edit",
                patch="not a unified diff",
            )
        assert "exact line counts" in messages[-1].content
        return CompleteAction(task_id=task_id, rationale="stop", summary="done")


def test_read_only_controller_runs_tool_then_completes_with_lifecycle_audit() -> None:
    task_id = uuid4()
    inspect = ListFilesAction(task_id=task_id, rationale="inspect", path=".")
    complete = CompleteAction(
        task_id=task_id,
        rationale="done",
        summary="The project contains one file.",
    )
    audit = MemoryAuditSink()
    config = load_config(Path("config/policy.example.toml"))
    controller = ReadOnlyController(
        model=FakeModel([inspect, complete]),
        policy=BaselinePolicy(),
        tools=_StubTools(),
        audit=audit,
        settings=config.task,
    )

    report = controller.run(task_id=task_id, task="inspect")

    assert report.status == "completed"
    assert report.tool_calls == 1
    assert report.files_read == ()
    assert [event.event_type for event in audit.events] == [
        "task_started",
        "action_decided",
        "tool_finished",
        "action_decided",
        "task_completed",
    ]


def test_read_only_controller_stops_repeated_actions() -> None:
    task_id = uuid4()
    repeated = [
        ListFilesAction(task_id=task_id, rationale="again", path=".") for _ in range(4)
    ]
    config = load_config(Path("config/policy.example.toml"))
    settings = config.task.model_copy(update={"max_repeated_actions": 2})
    audit = MemoryAuditSink()
    controller = ReadOnlyController(
        model=FakeModel(repeated),
        policy=BaselinePolicy(),
        tools=_StubTools(),
        audit=audit,
        settings=settings,
    )

    with pytest.raises(ControllerLimitError, match="repeated"):
        controller.run(task_id=task_id, task="inspect")

    assert audit.events[-1].event_type == "task_failed"


def test_read_only_controller_retries_bounded_invalid_model_action() -> None:
    task_id = uuid4()
    config = load_config(Path("config/policy.example.toml"))
    audit = MemoryAuditSink()
    controller = ReadOnlyController(
        model=_RecoveringModel(),
        policy=BaselinePolicy(),
        tools=_StubTools(),
        audit=audit,
        settings=config.task,
    )

    report = controller.run(task_id=task_id, task="inspect")

    assert report.model_failures == 1
    assert [event.event_type for event in audit.events] == [
        "task_started",
        "model_failed",
        "action_decided",
        "task_completed",
    ]


def test_controller_gives_safe_specific_correction_for_invalid_patch() -> None:
    task_id = uuid4()
    config = load_config(Path("config/policy.example.toml"))
    audit = MemoryAuditSink()
    controller = ReadOnlyController(
        model=_PatchCorrectionModel(),
        policy=BaselinePolicy(config.tools.apply_patch),
        tools=_StubTools(),
        audit=audit,
        settings=config.task,
    )

    report = controller.run(task_id=task_id, task="edit")

    assert report.denied_actions == 1
    assert report.tool_calls == 0
