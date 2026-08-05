# SPDX-License-Identifier: MPL-2.0

import json
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import pytest

from ulg.actions import (
    Action,
    ApplyPatchAction,
    CompleteAction,
    ListFilesAction,
    ShowDiffAction,
)
from ulg.cli import main
from ulg.config.models import ModelSettings
from ulg.model import ChatMessage, ModelProtocolError
from ulg.sandbox import SandboxResult


def test_dry_run_cli(capsys: object) -> None:
    assert main(["dry-run"]) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    payload = json.loads(output)
    assert payload["action_type"] == "list_files"
    assert payload["decision"] == "allow"
    assert payload["executed"] is False


class _ImmediateModel:
    def __init__(self, settings: ModelSettings) -> None:
        del settings
        self.calls = 0

    def propose(self, *, task_id: UUID, messages: Sequence[ChatMessage]) -> Action:
        del messages
        self.calls += 1
        if self.calls == 1:
            return ListFilesAction(task_id=task_id, rationale="inspect", path=".")
        return CompleteAction(
            task_id=task_id,
            rationale="done",
            summary="Inspection completed.",
        )

    def close(self) -> None:
        pass


class _InterruptModel(_ImmediateModel):
    closed = False

    def propose(self, *, task_id: UUID, messages: Sequence[ChatMessage]) -> Action:
        del task_id, messages
        raise KeyboardInterrupt

    def close(self) -> None:
        type(self).closed = True


class _CodingModel(_ImmediateModel):
    def propose(self, *, task_id: UUID, messages: Sequence[ChatMessage]) -> Action:
        del messages
        self.calls += 1
        if self.calls == 1:
            return ApplyPatchAction(
                task_id=task_id,
                rationale="update readme",
                patch=(
                    "--- a/README.md\n+++ b/README.md\n@@ -1,1 +1,1 @@\n-old\n+new\n"
                ),
            )
        if self.calls == 2:
            return ShowDiffAction(task_id=task_id, rationale="review")
        return CompleteAction(
            task_id=task_id,
            rationale="done",
            summary="Updated README.md.",
        )


class _CancelAfterPatchModel(_CodingModel):
    def propose(self, *, task_id: UUID, messages: Sequence[ChatMessage]) -> Action:
        if self.calls == 0:
            return super().propose(task_id=task_id, messages=messages)
        raise KeyboardInterrupt


class _FailAfterPatchModel(_CodingModel):
    def propose(self, *, task_id: UUID, messages: Sequence[ChatMessage]) -> Action:
        if self.calls == 0:
            return super().propose(task_id=task_id, messages=messages)
        raise ModelProtocolError("transport_error", "offline")


class _CloseFailureModel(_CodingModel):
    def close(self) -> None:
        raise OSError("close failed")


class _SuccessfulSandbox:
    def __init__(self, settings: object, recipes: object) -> None:
        del settings, recipes

    def run(self, *, recipe_name: str, workspace: Path) -> SandboxResult:
        assert workspace.stat().st_mode & 0o777 == 0o555
        return SandboxResult(
            recipe_name=recipe_name,
            recipe_digest="a" * 64,
            image_digest=f"sha256:{'b' * 64}",
            sandbox_profile_digest="c" * 64,
            ok=True,
            exit_code=0,
            duration_ms=12,
            output="passed\n",
            output_bytes=7,
        )


def test_sandbox_run_cli_audits_metadata_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "test_app.py").write_text("def test_ok(): assert True\n")
    state = tmp_path / "state"
    monkeypatch.setattr("ulg.cli.RootlessDockerRunner", _SuccessfulSandbox)

    exit_code = main(
        [
            "sandbox-run",
            "--workspace",
            str(source),
            "--recipe",
            "test",
            "--state-dir",
            str(state),
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert list((state / "workspaces").iterdir()) == []
    audit_file = next((state / "audit").glob("*.jsonl"))
    events = [json.loads(line) for line in audit_file.read_text().splitlines()]
    assert [event["event_type"] for event in events] == [
        "task_started",
        "sandbox_finished",
        "task_completed",
        "workspace_discarded",
    ]
    sandbox_event = events[1]
    assert sandbox_event["image_digest"] == f"sha256:{'b' * 64}"
    assert "output" not in sandbox_event


def test_inspect_cli_uses_snapshot_persists_audit_and_cleans_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("safe")
    state = tmp_path / "state"
    monkeypatch.setattr("ulg.cli.OllamaModel", _ImmediateModel)

    exit_code = main(
        [
            "inspect",
            "--workspace",
            str(source),
            "--task",
            "inspect",
            "--state-dir",
            str(state),
        ]
    )

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "completed"
    assert report["tool_calls"] == 1
    assert report["files_read"] == []
    assert (source / "README.md").read_text() == "safe"
    assert list((state / "workspaces").iterdir()) == []
    audit_files = list((state / "audit").glob("*.jsonl"))
    assert len(audit_files) == 1
    event_types = [
        json.loads(line)["event_type"]
        for line in audit_files[0].read_text().splitlines()
    ]
    assert event_types == [
        "task_started",
        "action_decided",
        "tool_finished",
        "action_decided",
        "task_completed",
    ]


def test_inspect_cli_cancellation_closes_model_and_cleans_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("safe")
    state = tmp_path / "state"
    _InterruptModel.closed = False
    monkeypatch.setattr("ulg.cli.OllamaModel", _InterruptModel)

    exit_code = main(
        [
            "inspect",
            "--workspace",
            str(source),
            "--task",
            "inspect",
            "--state-dir",
            str(state),
        ]
    )

    assert exit_code == 130
    assert "task cancelled" in capsys.readouterr().err
    assert _InterruptModel.closed is True
    assert list((state / "workspaces").iterdir()) == []


def test_run_cli_exports_patch_without_modifying_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("old\n")
    state = tmp_path / "state"
    output = tmp_path / "change.patch"
    monkeypatch.setattr("ulg.cli.OllamaModel", _CodingModel)

    exit_code = main(
        [
            "run",
            "--workspace",
            str(source),
            "--task",
            "update readme",
            "--output",
            str(output),
            "--state-dir",
            str(state),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["changed_files"] == ["README.md"]
    assert payload["report"]["generation"] == 1
    assert payload["diff"] == output.read_text()
    assert (source / "README.md").read_text() == "old\n"
    assert list((state / "workspaces").iterdir()) == []
    audit_file = next((state / "audit").glob("*.jsonl"))
    events = [json.loads(line) for line in audit_file.read_text().splitlines()]
    assert events[-2]["event_type"] == "patch_exported"
    assert events[-2]["source_tree_sha256"]
    assert events[-2]["generation_tree_sha256"]
    assert events[-2]["recovered_after_failure"] is False
    assert events[-1]["event_type"] == "workspace_discarded"
    assert events[-1]["reason_code"] == "completed"
    assert events[-1]["patch_exported"] is True


@pytest.mark.parametrize(
    ("model_type", "expected_exit", "reason"),
    [
        (_CancelAfterPatchModel, 130, "cancelled"),
        (_FailAfterPatchModel, 2, "failed"),
    ],
)
def test_run_cli_exports_last_complete_generation_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    model_type: type[_CodingModel],
    expected_exit: int,
    reason: str,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("old\n")
    state = tmp_path / "state"
    output = tmp_path / "recovery.patch"
    monkeypatch.setattr("ulg.cli.OllamaModel", model_type)

    exit_code = main(
        [
            "run",
            "--workspace",
            str(source),
            "--task",
            "update then fail",
            "--output",
            str(output),
            "--state-dir",
            str(state),
        ]
    )

    assert exit_code == expected_exit
    assert output.exists()
    assert "+new" in output.read_text()
    assert (source / "README.md").read_text() == "old\n"
    assert list((state / "workspaces").iterdir()) == []
    assert "recovery patch exported" in capsys.readouterr().err
    audit_file = next((state / "audit").glob("*.jsonl"))
    events = [json.loads(line) for line in audit_file.read_text().splitlines()]
    exported = next(
        event for event in events if event["event_type"] == "patch_exported"
    )
    assert exported["recovered_after_failure"] is True
    assert events[-1]["event_type"] == "workspace_discarded"
    assert events[-1]["reason_code"] == reason
    assert events[-1]["patch_exported"] is True


def test_run_cli_refuses_patch_export_inside_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("old\n")
    state = tmp_path / "state"
    output = source / "change.patch"
    monkeypatch.setattr("ulg.cli.OllamaModel", _CodingModel)

    exit_code = main(
        [
            "run",
            "--workspace",
            str(source),
            "--task",
            "update readme",
            "--output",
            str(output),
            "--state-dir",
            str(state),
        ]
    )

    assert exit_code == 2
    assert not output.exists()
    assert (source / "README.md").read_text() == "old\n"
    assert list((state / "workspaces").iterdir()) == []
    assert "protected root" in capsys.readouterr().err


def test_run_cli_refuses_application_state_inside_original_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("old\n")
    output = tmp_path / "change.patch"
    monkeypatch.setattr("ulg.cli.OllamaModel", _CodingModel)

    exit_code = main(
        [
            "run",
            "--workspace",
            str(source),
            "--task",
            "update readme",
            "--output",
            str(output),
            "--state-dir",
            str(source),
        ]
    )

    assert exit_code == 2
    assert not (source / "workspaces").exists()
    assert not (source / "audit").exists()
    assert not output.exists()
    assert "state cannot be inside" in capsys.readouterr().err


def test_run_cli_cleanup_survives_model_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("old\n")
    state = tmp_path / "state"
    output = tmp_path / "change.patch"
    monkeypatch.setattr("ulg.cli.OllamaModel", _CloseFailureModel)

    exit_code = main(
        [
            "run",
            "--workspace",
            str(source),
            "--task",
            "update readme",
            "--output",
            str(output),
            "--state-dir",
            str(state),
        ]
    )

    assert exit_code == 0
    assert output.exists()
    assert list((state / "workspaces").iterdir()) == []
    assert "model client close failed" in capsys.readouterr().err
