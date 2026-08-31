# SPDX-License-Identifier: MPL-2.0

import os
from pathlib import Path
from uuid import uuid4

import pytest

from ulg.audit import (
    ActionDecisionEvent,
    AuditReadError,
    JsonlAuditSink,
    SandboxFinishedEvent,
    TaskLifecycleEvent,
    ToolFinishedEvent,
    read_audit_summary,
)
from ulg.policy import DecisionKind


def test_jsonl_audit_sink_refuses_symlink_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("unchanged")
    audit_path = tmp_path / "audit.jsonl"
    os.symlink(target, audit_path)
    sink = JsonlAuditSink(audit_path)

    with pytest.raises(ValueError, match="safely"):
        sink.append(TaskLifecycleEvent(task_id=uuid4(), event_type="task_started"))

    assert target.read_text() == "unchanged"


def test_audit_reader_builds_bounded_redacted_summary(tmp_path: Path) -> None:
    task_id = uuid4()
    path = tmp_path / "audit.jsonl"
    sink = JsonlAuditSink(path)
    sink.append(TaskLifecycleEvent(task_id=task_id, event_type="task_started"))
    action_id = uuid4()
    sink.append(
        ActionDecisionEvent(
            task_id=task_id,
            action_id=action_id,
            action_type="run_task",
            decision=DecisionKind.ALLOW,
            reason_code="allowed",
        )
    )
    sink.append(
        ToolFinishedEvent(
            task_id=task_id,
            action_id=action_id,
            action_type="run_task",
            ok=True,
            truncated=False,
        )
    )
    sink.append(
        SandboxFinishedEvent(
            task_id=task_id,
            action_id=action_id,
            recipe_name="test",
            recipe_digest="a" * 64,
            image_digest=f"sha256:{'b' * 64}",
            sandbox_profile_digest="c" * 64,
            ok=True,
            timed_out=False,
            cancelled=False,
            duration_ms=1,
            output_bytes=7,
            output_truncated=False,
        )
    )

    summary = read_audit_summary(path, task_id=task_id)

    assert summary.proposed_actions == 1
    assert summary.executed_actions == 1
    assert summary.verified_checks == 1
    assert summary.failures == 0
    assert summary.timeline[-1].recipe_name == "test"
    assert "output" not in summary.model_dump_json()


def test_audit_reader_tolerates_only_a_truncated_final_event(tmp_path: Path) -> None:
    task_id = uuid4()
    path = tmp_path / "audit.jsonl"
    path.write_text(
        TaskLifecycleEvent(task_id=task_id, event_type="task_started").model_dump_json()
        + '\n{"schema_version":'
    )

    summary = read_audit_summary(path, task_id=task_id)

    assert summary.events_total == 1
    assert summary.incomplete_tail is True

    path.write_text("{not-json}\n")
    with pytest.raises(AuditReadError, match="malformed"):
        read_audit_summary(path, task_id=task_id)
