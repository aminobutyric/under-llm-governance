# SPDX-License-Identifier: MPL-2.0

import os
from pathlib import Path
from uuid import uuid4

import pytest

from ulg.config import load_config
from ulg.workspace import (
    PathSecurityError,
    SecureRoot,
    SnapshotError,
    SnapshotWorkspaceManager,
)


def test_snapshot_excludes_secrets_git_metadata_and_gitignored_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / ".gitignore").write_text("ignored.txt\ncache/\n")
    (source / "visible.txt").write_text("visible")
    (source / "ignored.txt").write_text("ignored")
    (source / ".env").write_text("TOKEN=secret")
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("secret remote")
    (source / "cache").mkdir()
    (source / "cache" / "item").write_text("cache")
    (source / "nested").mkdir()
    (source / "nested" / ".gitignore").write_text("*.tmp\n")
    (source / "nested" / "drop.tmp").write_text("ignored")
    (source / "nested" / "keep.py").write_text("print('ok')")

    config = load_config(Path("config/policy.example.toml"))
    manager = SnapshotWorkspaceManager(tmp_path / "state", config.workspace)
    workspace = manager.create(source=source, task_id=uuid4())

    assert (workspace.root / "visible.txt").read_text() == "visible"
    assert (workspace.root / "nested" / "keep.py").exists()
    assert not (workspace.root / "ignored.txt").exists()
    assert not (workspace.root / ".env").exists()
    assert not (workspace.root / ".git").exists()
    assert not (workspace.root / "cache").exists()
    assert not (workspace.root / "nested" / "drop.tmp").exists()

    (workspace.root / "visible.txt").write_text("changed snapshot")
    assert (source / "visible.txt").read_text() == "visible"

    manager.discard(workspace)
    assert not workspace.root.parent.exists()


def test_snapshot_records_write_once_verified_source_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "run.sh").write_text("#!/bin/sh\n")
    (source / "run.sh").chmod(0o755)
    config = load_config(Path("config/policy.example.toml"))
    manager = SnapshotWorkspaceManager(tmp_path / "state", config.workspace)
    workspace = manager.create(source=source, task_id=uuid4())

    manifest = manager.read_manifest(workspace, verify=True)

    assert manifest.generation == 0
    assert manifest.parent_tree_sha256 is None
    assert manifest.file_count == 1
    assert manifest.entries[0].path == "run.sh"
    assert manifest.entries[0].executable is True
    assert manifest.total_bytes == len("#!/bin/sh\n")
    with pytest.raises(SnapshotError, match="cannot be created"):
        manager.write_manifest(manifest)


def test_manifest_verification_detects_generation_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "safe.txt").write_text("safe")
    config = load_config(Path("config/policy.example.toml"))
    manager = SnapshotWorkspaceManager(tmp_path / "state", config.workspace)
    workspace = manager.create(source=source, task_id=uuid4())

    (workspace.root / "safe.txt").write_text("tampered")

    with pytest.raises(SnapshotError, match="no longer matches"):
        manager.read_manifest(workspace, verify=True)


def test_snapshot_enforces_file_count_quota(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "one").touch()
    (source / "two").touch()
    config = load_config(Path("config/policy.example.toml"))
    settings = config.workspace.model_copy(update={"max_files": 1})
    manager = SnapshotWorkspaceManager(tmp_path / "state", settings)

    with pytest.raises(SnapshotError, match="file-count quota"):
        manager.create(source=source, task_id=uuid4())


def test_snapshot_enforces_manifest_byte_quota_and_cleans_task(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "safe.txt").write_text("safe")
    task_id = uuid4()
    config = load_config(Path("config/policy.example.toml"))
    settings = config.workspace.model_copy(update={"max_manifest_bytes": 16})
    state = tmp_path / "state"
    manager = SnapshotWorkspaceManager(state, settings)

    with pytest.raises(SnapshotError, match="manifest exceeds byte limit"):
        manager.create(source=source, task_id=task_id)

    assert not (state / task_id.hex).exists()


def test_snapshot_refuses_application_state_inside_source_before_writing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "safe.txt").write_text("safe")
    state = source / ".ulg-state"
    config = load_config(Path("config/policy.example.toml"))
    manager = SnapshotWorkspaceManager(state, config.workspace)

    with pytest.raises(SnapshotError, match="inside the source"):
        manager.create(source=source, task_id=uuid4())

    assert not state.exists()


def test_snapshot_rejects_non_excluded_symlink_and_cleans_staging(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    os.symlink("/etc/passwd", source / "escape")
    task_id = uuid4()
    config = load_config(Path("config/policy.example.toml"))
    state = tmp_path / "state"
    manager = SnapshotWorkspaceManager(state, config.workspace)

    with pytest.raises(SnapshotError, match="symbolic link"):
        manager.create(source=source, task_id=task_id)

    assert not (state / task_id.hex).exists()


def test_snapshot_enforces_total_byte_quota(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.txt").write_bytes(b"1234")
    config = load_config(Path("config/policy.example.toml"))
    settings = config.workspace.model_copy(update={"max_bytes": 3})
    manager = SnapshotWorkspaceManager(tmp_path / "state", settings)

    with pytest.raises(SnapshotError, match="byte quota"):
        manager.create(source=source, task_id=uuid4())


def test_snapshot_rejects_special_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    os.mkfifo(source / "pipe")
    config = load_config(Path("config/policy.example.toml"))
    manager = SnapshotWorkspaceManager(tmp_path / "state", config.workspace)

    with pytest.raises(SnapshotError, match="special file"):
        manager.create(source=source, task_id=uuid4())


def test_secure_root_refuses_symlink_file(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    os.symlink("/etc/passwd", root / "escape")

    with SecureRoot(root) as secure_root, pytest.raises(PathSecurityError):
        secure_root.open_regular_file("escape")


def test_secure_root_fails_if_file_becomes_symlink_during_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    safe = root / "safe.txt"
    safe.write_text("safe")
    original_open = os.open
    swapped = False

    def racing_open(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "safe.txt" and dir_fd is not None and not swapped:
            swapped = True
            safe.rename(root / "original.txt")
            os.symlink("/etc/passwd", safe)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("ulg.workspace.paths.os.open", racing_open)

    with SecureRoot(root) as secure_root, pytest.raises(PathSecurityError):
        secure_root.open_regular_file("safe.txt")

    assert swapped is True


def test_sealed_sandbox_generation_remains_verified_and_discardable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "nested").mkdir()
    (source / "nested" / "safe.txt").write_text("safe")
    config = load_config(Path("config/policy.example.toml"))
    manager = SnapshotWorkspaceManager(tmp_path / "state", config.workspace)
    workspace = manager.create(source=source, task_id=uuid4())

    manager.seal_for_sandbox(workspace)

    assert manager.read_manifest(workspace, verify=True).file_count == 1
    assert workspace.root.stat().st_mode & 0o777 == 0o555
    assert (workspace.root / "nested" / "safe.txt").stat().st_mode & 0o777 == 0o444
    manager.discard(workspace)
    assert not workspace.root.parent.exists()
