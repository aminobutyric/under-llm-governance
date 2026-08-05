# SPDX-License-Identifier: MPL-2.0

from pathlib import Path
from uuid import uuid4

from ulg.actions import ApplyPatchAction, ReadFileAction, RunTaskAction, ShowDiffAction
from ulg.config import load_config
from ulg.policy import BaselinePolicy, DecisionKind
from ulg.sandbox import SandboxResult
from ulg.tools import CodingTools
from ulg.workspace import SnapshotWorkspaceManager

UPDATE_PATCH = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-print('old')
+print('new')
"""

DELETE_PATCH = """--- a/app.py
+++ /dev/null
@@ -1,1 +0,0 @@
-print('old')
"""


def test_coding_tools_publish_generation_and_read_from_new_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('old')\n")
    config = load_config(Path("config/policy.example.toml"))
    task_id = uuid4()
    manager = SnapshotWorkspaceManager(tmp_path / "state", config.workspace)
    workspace = manager.create(source=source, task_id=task_id)
    tools = CodingTools(
        workspace,
        manager,
        config.tools,
        original_root=source,
    )

    apply_action = ApplyPatchAction(
        task_id=task_id,
        rationale="update app",
        patch=UPDATE_PATCH,
    )
    result = tools.execute(apply_action)

    assert result.ok is True
    assert result.type == "apply_patch_result"
    assert tools.workspace.generation == 1
    read = tools.execute(
        ReadFileAction(task_id=task_id, rationale="verify", path="app.py")
    )
    assert read.type == "read_file_result"
    assert read.content == "print('new')\n"
    shown = tools.execute(ShowDiffAction(task_id=task_id, rationale="review"))
    assert shown.type == "show_diff_result"
    assert "-print('old')" in shown.diff
    assert "+print('new')" in shown.diff
    assert (source / "app.py").read_text() == "print('old')\n"


def test_patch_policy_allows_small_update_and_asks_for_delete() -> None:
    config = load_config(Path("config/policy.example.toml"))
    policy = BaselinePolicy(config.tools.apply_patch)
    task_id = uuid4()

    update = policy.evaluate(
        ApplyPatchAction(task_id=task_id, rationale="update", patch=UPDATE_PATCH)
    )
    deletion = policy.evaluate(
        ApplyPatchAction(task_id=task_id, rationale="delete", patch=DELETE_PATCH)
    )

    assert update.kind is DecisionKind.ALLOW
    assert deletion.kind is DecisionKind.ASK


def test_run_task_policy_asks_only_for_allowlisted_recipe() -> None:
    config = load_config(Path("config/policy.example.toml"))
    policy = BaselinePolicy(config.tools.apply_patch, config.tools.run_task)
    task_id = uuid4()

    allowed = policy.evaluate(
        RunTaskAction(task_id=task_id, rationale="verify", recipe_name="test")
    )
    unknown = policy.evaluate(
        RunTaskAction(task_id=task_id, rationale="verify", recipe_name="deploy")
    )
    unavailable = BaselinePolicy().evaluate(
        RunTaskAction(task_id=task_id, rationale="verify", recipe_name="test")
    )

    assert allowed.kind is DecisionKind.ASK
    assert allowed.reason_code == "recipe_requires_approval"
    assert unknown.kind is DecisionKind.DENY
    assert unknown.reason_code == "recipe_not_allowed"
    assert unavailable.kind is DecisionKind.DENY
    assert unavailable.reason_code == "run_policy_unavailable"


def test_coding_tools_return_bounded_patch_correction(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("actual\n")
    config = load_config(Path("config/policy.example.toml"))
    task_id = uuid4()
    manager = SnapshotWorkspaceManager(tmp_path / "state", config.workspace)
    workspace = manager.create(source=source, task_id=task_id)
    tools = CodingTools(
        workspace,
        manager,
        config.tools,
        original_root=source,
    )
    stale = ApplyPatchAction(
        task_id=task_id,
        rationale="update app",
        patch=("--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n-expected\n+new\n"),
    )

    result = tools.execute(stale)

    assert result.type == "apply_patch_result"
    assert result.ok is False
    assert result.error_code == "patch_rejected"
    assert result.correction is not None
    assert "context does not match" in result.correction
    assert len(result.correction) <= 500
    assert tools.workspace.generation == 0


def test_coding_tools_execute_only_runner_selected_recipe(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "test_app.py").write_text("def test_ok(): assert True\n")
    config = load_config(Path("config/policy.example.toml"))
    task_id = uuid4()
    manager = SnapshotWorkspaceManager(tmp_path / "state", config.workspace)
    workspace = manager.create(source=source, task_id=task_id)
    sandbox = _FakeSandbox()
    tools = CodingTools(
        workspace,
        manager,
        config.tools,
        original_root=source,
        sandbox=sandbox,
    )

    result = tools.execute(
        RunTaskAction(task_id=task_id, rationale="verify", recipe_name="test")
    )

    assert result.type == "run_task_result"
    assert result.ok is True
    assert result.recipe_name == "test"
    assert sandbox.calls == [("test", workspace.root)]
    assert manager.read_manifest(workspace, verify=True).file_count == 1


class _FakeSandbox:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def run(self, *, recipe_name: str, workspace: Path) -> SandboxResult:
        self.calls.append((recipe_name, workspace))
        return SandboxResult(
            recipe_name=recipe_name,
            recipe_digest="a" * 64,
            image_digest=f"sha256:{'b' * 64}",
            sandbox_profile_digest="c" * 64,
            ok=True,
            exit_code=0,
            duration_ms=10,
            output="passed\n",
            output_bytes=7,
        )
