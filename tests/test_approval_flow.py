# SPDX-License-Identifier: MPL-2.0

from io import StringIO
from pathlib import Path
from uuid import uuid4

from ulg.actions import ApplyPatchAction, CompleteAction, RunTaskAction
from ulg.approval import (
    ApprovalResolution,
    ScopedGrantStore,
    TerminalApprovalService,
    build_approval_request,
)
from ulg.audit import MemoryAuditSink
from ulg.config import load_config
from ulg.controller import ReadOnlyController
from ulg.model import FakeModel
from ulg.policy import BaselinePolicy
from ulg.sandbox import SandboxResult
from ulg.tools import CodingTools
from ulg.workspace import SnapshotWorkspaceManager

DELETE_PATCH = """--- a/old.txt
+++ /dev/null
@@ -1,1 +0,0 @@
-secret-looking source text
"""


class _Approval:
    def __init__(self, resolution: ApprovalResolution) -> None:
        self.resolution = resolution
        self.requests: list[object] = []

    def request(self, request: object) -> ApprovalResolution:
        self.requests.append(request)
        return self.resolution


class _Sandbox:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, *, recipe_name: str, workspace: Path) -> SandboxResult:
        del workspace
        self.calls.append(recipe_name)
        return SandboxResult(
            recipe_name=recipe_name,
            recipe_digest="a" * 64,
            image_digest=f"sha256:{'b' * 64}",
            sandbox_profile_digest="c" * 64,
            ok=True,
            exit_code=0,
            duration_ms=5,
            output="passed\n",
            output_bytes=7,
        )


def _coding_tools(tmp_path: Path, task_id: object, sandbox: _Sandbox | None = None):
    from uuid import UUID

    assert isinstance(task_id, UUID)
    source = tmp_path / "source"
    source.mkdir()
    (source / "old.txt").write_text("secret-looking source text\n")
    config = load_config(Path("config/policy.example.toml"))
    manager = SnapshotWorkspaceManager(tmp_path / "state", config.workspace)
    workspace = manager.create(source=source, task_id=task_id)
    tools = CodingTools(
        workspace,
        manager,
        config.tools,
        original_root=source,
        sandbox=sandbox,
    )
    return config, tools, source


def test_exact_patch_approval_executes_and_audits_without_touching_original(
    tmp_path: Path,
) -> None:
    task_id = uuid4()
    deletion = ApplyPatchAction(
        task_id=task_id,
        rationale="model prose is not trusted",
        patch=DELETE_PATCH,
    )
    complete = CompleteAction(task_id=task_id, rationale="done", summary="done")
    config, tools, source = _coding_tools(tmp_path, task_id)
    approval = _Approval(ApprovalResolution.APPROVE_ONCE)
    audit = MemoryAuditSink()
    controller = ReadOnlyController(
        model=FakeModel([deletion, complete]),
        policy=BaselinePolicy(config.tools.apply_patch, config.tools.run_task),
        tools=tools,
        audit=audit,
        settings=config.task,
        config=config,
        approval=approval,
        grants=ScopedGrantStore(),
    )

    report = controller.run(task_id=task_id, task="remove the old file")

    assert report.generation == 1
    assert report.changed_files == ("old.txt",)
    assert (source / "old.txt").read_text() == "secret-looking source text\n"
    assert [event.event_type for event in audit.events] == [
        "task_started",
        "action_decided",
        "approval_requested",
        "approval_resolved",
        "grant_issued",
        "grant_consumed",
        "tool_finished",
        "workspace_generation_published",
        "action_decided",
        "task_completed",
    ]


def test_recipe_grant_reuses_bounded_authority_without_reprompting(
    tmp_path: Path,
) -> None:
    task_id = uuid4()
    first = RunTaskAction(task_id=task_id, rationale="first", recipe_name="test")
    second = RunTaskAction(task_id=task_id, rationale="second", recipe_name="test")
    complete = CompleteAction(task_id=task_id, rationale="done", summary="done")
    sandbox = _Sandbox()
    config, tools, _ = _coding_tools(tmp_path, task_id, sandbox)
    approval = _Approval(ApprovalResolution.APPROVE_RECIPE)
    audit = MemoryAuditSink()
    controller = ReadOnlyController(
        model=FakeModel([first, second, complete]),
        policy=BaselinePolicy(config.tools.apply_patch, config.tools.run_task),
        tools=tools,
        audit=audit,
        settings=config.task,
        config=config,
        approval=approval,
        grants=ScopedGrantStore(),
    )

    report = controller.run(task_id=task_id, task="verify twice")

    assert report.tool_calls == 2
    assert report.approved_actions == 2
    assert report.sandbox_runs == 2
    assert report.successful_sandbox_runs == 2
    assert sandbox.calls == ["test", "test"]
    assert len(approval.requests) == 1
    event_types = [event.event_type for event in audit.events]
    assert event_types.count("approval_requested") == 1
    assert event_types.count("grant_issued") == 1
    assert event_types.count("grant_consumed") == 2
    assert event_types.count("sandbox_finished") == 2


def test_denied_approval_does_not_execute_recipe(tmp_path: Path) -> None:
    task_id = uuid4()
    run = RunTaskAction(task_id=task_id, rationale="run", recipe_name="test")
    complete = CompleteAction(task_id=task_id, rationale="done", summary="done")
    sandbox = _Sandbox()
    config, tools, _ = _coding_tools(tmp_path, task_id, sandbox)
    audit = MemoryAuditSink()
    controller = ReadOnlyController(
        model=FakeModel([run, complete]),
        policy=BaselinePolicy(config.tools.apply_patch, config.tools.run_task),
        tools=tools,
        audit=audit,
        settings=config.task,
        config=config,
        approval=_Approval(ApprovalResolution.DENY),
        grants=ScopedGrantStore(),
    )

    report = controller.run(task_id=task_id, task="verify")

    assert report.tool_calls == 0
    assert report.denied_actions == 1
    assert sandbox.calls == []
    assert "grant_issued" not in [event.event_type for event in audit.events]


def test_replayed_recipe_action_is_rejected_audited_and_reprompted(
    tmp_path: Path,
) -> None:
    task_id = uuid4()
    replayed = RunTaskAction(
        task_id=task_id,
        rationale="model tries to reuse an approved action",
        recipe_name="test",
    )
    complete = CompleteAction(task_id=task_id, rationale="done", summary="contained")
    sandbox = _Sandbox()
    config, tools, source = _coding_tools(tmp_path, task_id, sandbox)
    decision = BaselinePolicy(run_settings=config.tools.run_task).evaluate(replayed)
    grants = ScopedGrantStore()
    grant = grants.issue_recipe(decision=decision, action=replayed, config=config)
    grants.consume_recipe(grant.grant_id, action=replayed, config=config)
    audit = MemoryAuditSink()
    controller = ReadOnlyController(
        model=FakeModel([replayed, complete]),
        policy=BaselinePolicy(config.tools.apply_patch, config.tools.run_task),
        tools=tools,
        audit=audit,
        settings=config.task,
        config=config,
        approval=_Approval(ApprovalResolution.DENY),
        grants=grants,
    )

    report = controller.run(task_id=task_id, task="verify")

    assert report.denied_actions == 1
    assert sandbox.calls == []
    assert (source / "old.txt").read_text() == "secret-looking source text\n"
    rejected = [event for event in audit.events if event.event_type == "grant_rejected"]
    assert len(rejected) == 1
    assert rejected[0].reason_code == "grant_action_replayed"  # type: ignore[union-attr]
    assert any(event.event_type == "approval_requested" for event in audit.events)


def test_terminal_patch_prompt_excludes_model_prose_and_raw_patch() -> None:
    config = load_config(Path("config/policy.example.toml"))
    action = ApplyPatchAction(
        task_id=uuid4(),
        rationale="\x1b[31mAPPROVE EVERYTHING\x1b[0m",
        patch=DELETE_PATCH,
    )
    decision = BaselinePolicy(config.tools.apply_patch).evaluate(action)
    request = build_approval_request(action=action, decision=decision, config=config)
    output = StringIO()
    service = TerminalApprovalService(input_fn=lambda: "y", output=output)

    assert service.request(request) is ApprovalResolution.APPROVE_ONCE
    rendered = output.getvalue()
    assert "old.txt" in rendered
    assert "delete" in rendered
    assert "APPROVE EVERYTHING" not in rendered
    assert "secret-looking source text" not in rendered
    assert "\x1b" not in rendered


def test_terminal_approval_fails_closed_on_invalid_input() -> None:
    config = load_config(Path("config/policy.example.toml"))
    action = RunTaskAction(task_id=uuid4(), rationale="run", recipe_name="test")
    decision = BaselinePolicy(run_settings=config.tools.run_task).evaluate(action)
    request = build_approval_request(action=action, decision=decision, config=config)
    output = StringIO()

    resolution = TerminalApprovalService(
        input_fn=lambda: "maybe", output=output
    ).request(request)

    assert resolution is ApprovalResolution.DENY
    assert "Trusted command" in output.getvalue()
    assert "network=none" in output.getvalue()


def test_terminal_explains_expired_grant_without_rendering_untrusted_data() -> None:
    output = StringIO()
    service = TerminalApprovalService(input_fn=lambda: "n", output=output)

    service.notify_grant_rejected("grant_expired")

    assert output.getvalue() == (
        "\nThe previous grant expired; fresh approval is required.\n"
    )
