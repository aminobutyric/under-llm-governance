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
    RunTaskAction,
    ShowDiffAction,
)
from ulg.cli import build_parser, main
from ulg.config.models import ModelSettings
from ulg.model import ChatMessage, ModelProtocolError
from ulg.sandbox import DockerPreflightError, SandboxResult


def test_dry_run_cli(capsys: object) -> None:
    assert main(["dry-run"]) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    payload = json.loads(output)
    assert payload["action_type"] == "list_files"
    assert payload["decision"] == "allow"
    assert payload["executed"] is False


def test_cli_paths_and_external_config_default_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Path("/trusted/ulg-policy.toml")
    monkeypatch.setenv("ULG_CONFIG", str(config))

    args = build_parser().parse_args(
        [
            "inspect",
            "--workspace",
            "../small-project",
            "--task",
            "explain",
        ]
    )

    assert args.workspace == Path("../small-project")
    assert args.config == config


class _ImmediateModel:
    def __init__(
        self,
        settings: ModelSettings,
        *,
        enable_run_task: bool = False,
        allowed_recipes: tuple[str, ...] = (),
    ) -> None:
        del settings, enable_run_task, allowed_recipes
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


class _CodingAndTestModel(_ImmediateModel):
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
            return RunTaskAction(
                task_id=task_id,
                rationale="run the trusted tests",
                recipe_name="test",
            )
        return CompleteAction(task_id=task_id, rationale="done", summary="done")


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


class _ResumeModel(_ImmediateModel):
    def propose(self, *, task_id: UUID, messages: Sequence[ChatMessage]) -> Action:
        del messages
        self.calls += 1
        if self.calls == 1:
            return ShowDiffAction(task_id=task_id, rationale="review retained changes")
        return CompleteAction(
            task_id=task_id,
            rationale="done",
            summary="Retained change is ready for export.",
        )


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


class _FailedPreflight:
    def check(self) -> object:
        raise DockerPreflightError("rootless Docker socket is unavailable")


def test_sandbox_preflight_error_has_actionable_guidance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("ulg.cli.RootlessDockerPreflight", _FailedPreflight)

    assert main(["sandbox-preflight"]) == 2

    error = capsys.readouterr().err
    assert "rootless user Docker service" in error
    assert "ulg sandbox-preflight" in error


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


def test_run_cli_approves_and_executes_model_requested_recipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("old\n")
    state = tmp_path / "state"
    output = tmp_path / "change.patch"
    monkeypatch.setattr("ulg.cli.OllamaModel", _CodingAndTestModel)
    monkeypatch.setattr("ulg.cli.RootlessDockerRunner", _SuccessfulSandbox)
    monkeypatch.setattr("builtins.input", lambda: "o")

    exit_code = main(
        [
            "run",
            "--workspace",
            str(source),
            "--task",
            "update and verify",
            "--output",
            str(output),
            "--state-dir",
            str(state),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)["report"]
    assert report["approved_actions"] == 1
    assert report["sandbox_runs"] == 1
    assert report["successful_sandbox_runs"] == 1
    assert "Approval required" in captured.err
    assert "Trusted command" in captured.err
    audit_file = next((state / "audit").glob("*.jsonl"))
    event_types = [
        json.loads(line)["event_type"] for line in audit_file.read_text().splitlines()
    ]
    assert "approval_requested" in event_types
    assert "grant_consumed" in event_types
    assert "sandbox_finished" in event_types


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
            "--failure-mode",
            "recover",
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


def test_run_cli_retains_failure_and_resume_exports_verified_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("old\n")
    state = tmp_path / "state"
    output = tmp_path / "resumed.patch"
    monkeypatch.setattr("ulg.cli.OllamaModel", _FailAfterPatchModel)

    assert (
        main(
            [
                "run",
                "--workspace",
                str(source),
                "--task",
                "update then resume",
                "--output",
                str(output),
                "--state-dir",
                str(state),
            ]
        )
        == 2
    )
    retained_error = capsys.readouterr().err
    task_file = next(
        path
        for path in (state / "tasks").glob("*.json")
        if not path.name.endswith(".grants.json")
    )
    retained = json.loads(task_file.read_text())
    task_id = retained["task_id"]
    assert retained["phase"] == "retry"
    assert retained["generation"] == 1
    assert "resume:" in retained_error
    assert not output.exists()

    monkeypatch.setattr("ulg.cli.OllamaModel", _ResumeModel)
    assert main(["resume", task_id, "--state-dir", str(state)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["task_id"] == task_id
    assert payload["state"] == "discard"
    assert "+new" in output.read_text()
    assert (source / "README.md").read_text() == "old\n"
    assert list((state / "workspaces").iterdir()) == []
    final_state = json.loads(task_file.read_text())
    assert final_state["phase"] == "discard"
    event_types = [
        json.loads(line)["event_type"]
        for line in (state / "audit" / f"{task_id}.jsonl").read_text().splitlines()
    ]
    assert "task_resumed" in event_types
    assert event_types[-1] == "workspace_discarded"


def test_resume_rejects_changed_configuration_and_keeps_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("old\n")
    state = tmp_path / "state"
    output = tmp_path / "change.patch"
    config_copy = tmp_path / "policy.toml"
    config_copy.write_bytes(Path("config/policy.example.toml").read_bytes())
    monkeypatch.setattr("ulg.cli.OllamaModel", _FailAfterPatchModel)

    assert (
        main(
            [
                "run",
                "--workspace",
                str(source),
                "--task",
                "update then resume",
                "--output",
                str(output),
                "--config",
                str(config_copy),
                "--state-dir",
                str(state),
            ]
        )
        == 2
    )
    capsys.readouterr()
    task_file = next(
        path
        for path in (state / "tasks").glob("*.json")
        if not path.name.endswith(".grants.json")
    )
    task_id = json.loads(task_file.read_text())["task_id"]
    config_copy.write_text(
        config_copy.read_text().replace("max_turns = 40", "max_turns = 41")
    )

    assert main(["resume", task_id, "--state-dir", str(state)]) == 2

    assert "configuration changed" in capsys.readouterr().err
    assert len(list((state / "workspaces").iterdir())) == 1
    assert main(["discard", task_id, "--state-dir", str(state)]) == 0
    assert list((state / "workspaces").iterdir()) == []


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
    retained = list((state / "workspaces").iterdir())
    assert len(retained) == 1
    assert "protected root" in capsys.readouterr().err

    task_payload = json.loads(next((state / "tasks").glob("*.json")).read_text())
    task_id = task_payload["task_id"]
    assert main(["discard", task_id, "--state-dir", str(state)]) == 0
    assert list((state / "workspaces").iterdir()) == []


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


def test_retained_task_diff_audit_and_explicit_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("old\n")
    state = tmp_path / "state"
    output = tmp_path / "change.patch"
    monkeypatch.setattr("ulg.cli.OllamaModel", _FailAfterPatchModel)
    assert (
        main(
            [
                "run",
                "--workspace",
                str(source),
                "--task",
                "update then review",
                "--output",
                str(output),
                "--state-dir",
                str(state),
            ]
        )
        == 2
    )
    run_error = capsys.readouterr().err
    task_payload = json.loads(
        next(
            path
            for path in (state / "tasks").glob("*.json")
            if not path.name.endswith(".grants.json")
        ).read_text()
    )
    task_id = task_payload["task_id"]
    assert "Ollama is unavailable" in run_error
    assert f"diff: ulg diff {task_id}" in run_error
    assert f"audit: ulg audit {task_id}" in run_error
    assert f"discard: ulg discard {task_id}" in run_error

    assert main(["diff", task_id, "--state-dir", str(state)]) == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["generation"] == 1
    assert diff["truncated"] is False
    assert "+new" in diff["diff"]

    assert main(["audit", task_id, "--state-dir", str(state)]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["task_id"] == task_id
    assert audit["proposed_actions"] == 1
    assert audit["executed_actions"] == 1
    timeline = json.dumps(audit["timeline"])
    assert "+new" not in timeline
    assert "--- a/README.md" not in timeline

    assert main(["clean", task_id, "--state-dir", str(state), "--yes"]) == 2
    assert "--include-retained" in capsys.readouterr().err
    assert (state / "workspaces" / UUID(task_id).hex).exists()

    assert (
        main(
            [
                "clean",
                task_id,
                "--state-dir",
                str(state),
                "--include-retained",
                "--older-than-days",
                "1",
                "--yes",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["deleted_task_ids"] == []

    assert (
        main(
            [
                "clean",
                task_id,
                "--state-dir",
                str(state),
                "--include-retained",
                "--yes",
            ]
        )
        == 0
    )
    cleaned = json.loads(capsys.readouterr().out)
    assert cleaned["deleted_task_ids"] == [task_id]
    assert cleaned["bytes_deleted"] > 0
    assert not (state / "workspaces" / UUID(task_id).hex).exists()
    assert not (state / "audit" / f"{task_id}.jsonl").exists()
    assert not (state / "tasks" / f"{UUID(task_id).hex}.json").exists()
    assert not (state / "tasks" / f"{UUID(task_id).hex}.lock").exists()
