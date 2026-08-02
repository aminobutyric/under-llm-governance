# SPDX-License-Identifier: MPL-2.0

import os
from pathlib import Path
from uuid import uuid4

import pytest

from ulg.audit import JsonlAuditSink, TaskLifecycleEvent


def test_jsonl_audit_sink_refuses_symlink_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("unchanged")
    audit_path = tmp_path / "audit.jsonl"
    os.symlink(target, audit_path)
    sink = JsonlAuditSink(audit_path)

    with pytest.raises(ValueError, match="safely"):
        sink.append(TaskLifecycleEvent(task_id=uuid4(), event_type="task_started"))

    assert target.read_text() == "unchanged"
