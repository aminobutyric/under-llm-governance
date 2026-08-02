# SPDX-License-Identifier: MPL-2.0

from pathlib import Path
from uuid import uuid4

import pytest

from ulg.config import load_config
from ulg.workspace import (
    PatchError,
    SnapshotWorkspaceManager,
    WorkspaceEditor,
    WorkspaceRef,
    parse_unified_diff,
)

MULTI_FILE_PATCH = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
-print('old')
+print('new')
 keep
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,1 @@
+new file
--- a/delete.txt
+++ /dev/null
@@ -1,1 +0,0 @@
-delete me
"""


def _workspace(
    tmp_path: Path, *, include_large_binary: bool = False
) -> tuple[SnapshotWorkspaceManager, WorkspaceRef]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('old')\nkeep\n")
    (source / "delete.txt").write_text("delete me\n")
    if include_large_binary:
        (source / "large.bin").write_bytes(b"\x00" * 1_100_000)
    config = load_config(Path("config/policy.example.toml"))
    manager = SnapshotWorkspaceManager(tmp_path / "state", config.workspace)
    return manager, manager.create(source=source, task_id=uuid4())


def test_parser_rejects_traversal_and_stale_hunk() -> None:
    traversal = """--- /dev/null
+++ b/../../escape
@@ -0,0 +1,1 @@
+bad
"""
    with pytest.raises(PatchError, match="escapes"):
        parse_unified_diff(traversal)

    patch = parse_unified_diff(
        """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
-expected
+replacement
"""
    )[0]
    with pytest.raises(PatchError, match="does not match"):
        patch.apply("different\n")


def test_editor_publishes_complete_generation_and_exports_reviewed_diff(
    tmp_path: Path,
) -> None:
    manager, workspace = _workspace(tmp_path)
    config = load_config(Path("config/policy.example.toml"))
    editor = WorkspaceEditor(
        manager,
        manager.exclusion_policy,
        config.tools.apply_patch,
        max_file_bytes=config.tools.read_file.max_bytes,
        original_root=tmp_path / "source",
    )

    summary = editor.apply(workspace, MULTI_FILE_PATCH)
    source_manifest = manager.read_manifest(workspace, verify=True)
    current_manifest = manager.read_manifest(summary.workspace, verify=True)

    assert summary.workspace.generation == 1
    assert (summary.workspace.root / "app.py").read_text() == "print('new')\nkeep\n"
    assert (summary.workspace.root / "new.txt").read_text() == "new file\n"
    assert not (summary.workspace.root / "delete.txt").exists()
    assert (workspace.root / "app.py").read_text() == "print('old')\nkeep\n"
    assert (tmp_path / "source" / "app.py").read_text() == "print('old')\nkeep\n"
    assert current_manifest.parent_tree_sha256 == source_manifest.tree_sha256
    assert summary.parent_tree_sha256 == source_manifest.tree_sha256
    assert summary.tree_sha256 == current_manifest.tree_sha256

    reviewed = editor.build_diff(summary.workspace)
    export = tmp_path / "change.patch"
    exported_bytes = editor.export_diff(summary.workspace, export)
    assert export.read_text() == reviewed
    assert exported_bytes == len(reviewed.encode())
    assert "--- a/app.py" in reviewed
    assert "+++ b/new.txt" in reviewed
    assert "+++ /dev/null" in reviewed


def test_export_refuses_original_and_task_workspace_destinations(
    tmp_path: Path,
) -> None:
    manager, workspace = _workspace(tmp_path)
    config = load_config(Path("config/policy.example.toml"))
    editor = WorkspaceEditor(
        manager,
        manager.exclusion_policy,
        config.tools.apply_patch,
        max_file_bytes=config.tools.read_file.max_bytes,
        original_root=tmp_path / "source",
    )
    summary = editor.apply(workspace, MULTI_FILE_PATCH)
    original_destination = tmp_path / "source" / "change.patch"
    task_destination = summary.workspace.root.parent / "change.patch"

    with pytest.raises(PatchError, match="protected root"):
        editor.export_diff(summary.workspace, original_destination)
    with pytest.raises(PatchError, match="protected root"):
        editor.export_diff(summary.workspace, task_destination)

    assert not original_destination.exists()
    assert not task_destination.exists()


def test_editor_removes_exact_incomplete_successor_before_retry(tmp_path: Path) -> None:
    manager, workspace = _workspace(tmp_path)
    incomplete = workspace.root.parent / "generation-1.staging"
    incomplete.mkdir()
    (incomplete / "partial.txt").write_text("partial")
    config = load_config(Path("config/policy.example.toml"))
    editor = WorkspaceEditor(
        manager,
        manager.exclusion_policy,
        config.tools.apply_patch,
        max_file_bytes=config.tools.read_file.max_bytes,
        original_root=tmp_path / "source",
    )

    summary = editor.apply(workspace, MULTI_FILE_PATCH)

    assert summary.workspace.generation == 1
    assert not incomplete.exists()
    assert not (summary.workspace.root / "partial.txt").exists()


def test_editor_enforces_generation_count_limit(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("old\n")
    config = load_config(Path("config/policy.example.toml"))
    settings = config.workspace.model_copy(update={"max_generations": 1})
    manager = SnapshotWorkspaceManager(tmp_path / "state", settings)
    workspace = manager.create(source=source, task_id=uuid4())
    editor = WorkspaceEditor(
        manager,
        manager.exclusion_policy,
        config.tools.apply_patch,
        max_file_bytes=config.tools.read_file.max_bytes,
        original_root=source,
    )
    first = editor.apply(
        workspace,
        "--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
    )

    with pytest.raises(PatchError, match="generation limit"):
        editor.apply(
            first.workspace,
            "--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n-new\n+newer\n",
        )

    assert not (first.workspace.root.parent / "generation-2").exists()


def test_editor_failure_never_exposes_partial_generation(tmp_path: Path) -> None:
    manager, workspace = _workspace(tmp_path)
    config = load_config(Path("config/policy.example.toml"))
    editor = WorkspaceEditor(
        manager,
        manager.exclusion_policy,
        config.tools.apply_patch,
        max_file_bytes=config.tools.read_file.max_bytes,
        original_root=tmp_path / "source",
    )
    patch = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-print('old')
+print('changed')
--- a/delete.txt
+++ b/delete.txt
@@ -1,1 +1,1 @@
-wrong context
+replacement
"""

    with pytest.raises(PatchError, match="does not match"):
        editor.apply(workspace, patch)

    assert (workspace.root / "app.py").read_text() == "print('old')\nkeep\n"
    assert not (workspace.root.parent / "generation-1").exists()
    assert not (workspace.root.parent / "generation-1.staging").exists()


def test_editor_refuses_secret_pattern_creation(tmp_path: Path) -> None:
    manager, workspace = _workspace(tmp_path)
    config = load_config(Path("config/policy.example.toml"))
    editor = WorkspaceEditor(
        manager,
        manager.exclusion_policy,
        config.tools.apply_patch,
        max_file_bytes=config.tools.read_file.max_bytes,
        original_root=tmp_path / "source",
    )
    patch = """--- /dev/null
+++ b/.env
@@ -0,0 +1,1 @@
+TOKEN=secret
"""

    with pytest.raises(PatchError, match="excluded"):
        editor.apply(workspace, patch)


def test_diff_hashes_unchanged_large_binary_without_loading_it_as_text(
    tmp_path: Path,
) -> None:
    manager, workspace = _workspace(tmp_path, include_large_binary=True)
    config = load_config(Path("config/policy.example.toml"))
    editor = WorkspaceEditor(
        manager,
        manager.exclusion_policy,
        config.tools.apply_patch,
        max_file_bytes=config.tools.read_file.max_bytes,
        original_root=tmp_path / "source",
    )

    summary = editor.apply(workspace, MULTI_FILE_PATCH)

    assert "app.py" in editor.build_diff(summary.workspace)
