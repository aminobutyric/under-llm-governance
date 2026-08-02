# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import uuid4

from ulg.config.models import ApplyPatchTool
from ulg.workspace.base import WorkspaceRef
from ulg.workspace.exclusions import ExclusionPolicy
from ulg.workspace.manager import SnapshotWorkspaceManager
from ulg.workspace.manifests import ManifestEntry
from ulg.workspace.patches import FilePatch, PatchError, parse_unified_diff
from ulg.workspace.paths import SecureRoot, relative_parts


@dataclass(frozen=True)
class PatchSummary:
    workspace: WorkspaceRef
    changed_files: tuple[str, ...]
    deleted_files: tuple[str, ...]
    parent_tree_sha256: str
    tree_sha256: str


class WorkspaceEditor:
    """Apply a validated diff to an unreferenced generation, then publish it."""

    def __init__(
        self,
        manager: SnapshotWorkspaceManager,
        exclusions: ExclusionPolicy,
        settings: ApplyPatchTool,
        *,
        max_file_bytes: int,
        original_root: Path,
    ) -> None:
        self._manager = manager
        self._exclusions = exclusions
        self._settings = settings
        self._max_file_bytes = max_file_bytes
        self._original_root = original_root

    def apply(self, workspace: WorkspaceRef, patch: str) -> PatchSummary:
        if len(patch.encode("utf-8")) > self._settings.max_patch_bytes:
            raise PatchError("patch exceeds configured byte limit")
        file_patches = parse_unified_diff(patch)
        if len(file_patches) > self._settings.max_changed_files:
            raise PatchError("patch changes too many files")
        for file_patch in file_patches:
            self._authorize_path(file_patch.path)

        next_generation = workspace.generation + 1
        if next_generation > self._manager.max_generations:
            raise PatchError("task exceeds workspace-generation limit")
        self._manager.remove_incomplete_next_generation(workspace)
        task_root = workspace.root.parent
        final_root = task_root / f"generation-{next_generation}"
        staging_root = task_root / f"generation-{next_generation}.staging"
        if final_root.exists() or staging_root.exists():
            raise PatchError("next workspace generation already exists")
        published = False
        try:
            copied = self._manager.copy_generation(
                workspace,
                staging_root,
                generation=next_generation,
            )
            for file_patch in file_patches:
                self._apply_file_patch(staging_root, file_patch)
            if copied.parent_tree_sha256 is None:
                raise PatchError("copied generation lost its parent manifest")
            manifest = self._manager.scan_staging_manifest(
                workspace,
                staging_root,
                generation=next_generation,
                parent_tree_sha256=copied.parent_tree_sha256,
            )
            os.rename(staging_root, final_root)
            published = True
            self._manager.write_manifest(manifest)
        except BaseException:
            if staging_root.exists():
                shutil.rmtree(staging_root)
            if published and final_root.exists():
                shutil.rmtree(final_root)
            raise
        next_workspace = WorkspaceRef(
            task_id=workspace.task_id,
            root=final_root,
            generation=next_generation,
        )
        return PatchSummary(
            workspace=next_workspace,
            changed_files=tuple(file_patch.path for file_patch in file_patches),
            deleted_files=tuple(
                file_patch.path
                for file_patch in file_patches
                if file_patch.operation == "delete"
            ),
            parent_tree_sha256=manifest.parent_tree_sha256 or "",
            tree_sha256=manifest.tree_sha256,
        )

    def build_diff(self, workspace: WorkspaceRef) -> str:
        original_workspace = WorkspaceRef(
            task_id=workspace.task_id,
            root=workspace.root.parent / "generation-0",
            generation=0,
        )
        original_manifest = self._manager.read_manifest(original_workspace, verify=True)
        current_manifest = self._manager.read_manifest(workspace, verify=True)
        original_root = original_workspace.root
        original = {entry.path: entry for entry in original_manifest.entries}
        current = {entry.path: entry for entry in current_manifest.entries}
        output: list[str] = []
        for path in sorted(set(original) | set(current)):
            before_record = original.get(path)
            after_record = current.get(path)
            if before_record == after_record:
                continue
            before = (
                None
                if before_record is None
                else self._read_changed_file(original_root, path, before_record)
            )
            after = (
                None
                if after_record is None
                else self._read_changed_file(workspace.root, path, after_record)
            )
            if before is not None and b"\x00" in before:
                raise PatchError(f"binary file changed unexpectedly: {path}")
            if after is not None and b"\x00" in after:
                raise PatchError(f"binary file changed unexpectedly: {path}")
            try:
                old_text = "" if before is None else before.decode("utf-8")
                new_text = "" if after is None else after.decode("utf-8")
            except UnicodeDecodeError as error:
                raise PatchError(f"changed file is not UTF-8 text: {path}") from error
            raw_lines = difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile="/dev/null" if before is None else f"a/{path}",
                tofile="/dev/null" if after is None else f"b/{path}",
                lineterm="\n",
            )
            for line in raw_lines:
                is_data_line = line.startswith(("+", "-", " ")) and not line.startswith(
                    ("+++ ", "--- ")
                )
                if is_data_line and not line.endswith("\n"):
                    output.append(f"{line}\n")
                    output.append("\\ No newline at end of file\n")
                else:
                    output.append(line)
        return "".join(output)

    def export_diff(
        self,
        workspace: WorkspaceRef,
        destination: Path,
        *,
        forbidden_roots: tuple[Path, ...] = (),
    ) -> int:
        payload = self.build_diff(workspace).encode("utf-8")
        if len(payload) > self._settings.max_patch_bytes:
            raise PatchError("reviewed diff exceeds export byte limit")
        try:
            file_fd = self._open_export_destination(
                destination,
                (self._original_root, workspace.root.parent, *forbidden_roots),
            )
        except OSError as error:
            raise PatchError("export destination must be a new safe file") from error
        try:
            view = memoryview(payload)
            while view:
                written = os.write(file_fd, view)
                if written <= 0:
                    raise PatchError("patch export made no progress")
                view = view[written:]
            os.fsync(file_fd)
        finally:
            os.close(file_fd)
        return len(payload)

    def _authorize_path(self, path: str) -> None:
        parts = relative_parts(path)
        candidate = PurePosixPath(*parts)
        if self._exclusions.is_permanently_excluded(candidate, is_directory=False):
            raise PatchError(f"patch targets an excluded path: {path}")
        for index in range(1, len(parts)):
            parent = PurePosixPath(*parts[:index])
            if self._exclusions.is_permanently_excluded(parent, is_directory=True):
                raise PatchError(f"patch targets an excluded directory: {path}")

    def _apply_file_patch(self, staging_root: Path, patch: FilePatch) -> None:
        target = staging_root.joinpath(*relative_parts(patch.path))
        source: str | None
        existing_mode = 0o600
        if target.exists():
            target_stat = target.lstat()
            if not stat.S_ISREG(target_stat.st_mode):
                raise PatchError(f"patch target is not a regular file: {patch.path}")
            if target_stat.st_size > self._max_file_bytes:
                raise PatchError(f"patch target exceeds file byte limit: {patch.path}")
            payload = target.read_bytes()
            if b"\x00" in payload:
                raise PatchError(f"patch target is binary: {patch.path}")
            try:
                source = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise PatchError(f"patch target is not UTF-8: {patch.path}") from error
            existing_mode = 0o700 if target_stat.st_mode & 0o111 else 0o600
        else:
            source = None
        result = patch.apply(source)
        if result is None:
            target.unlink()
            self._remove_empty_parents(target.parent, staging_root)
            return
        encoded = result.encode("utf-8")
        if len(encoded) > self._max_file_bytes:
            raise PatchError(f"patched file exceeds file byte limit: {patch.path}")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = target.parent / f".ulg-patch-{uuid4().hex}.tmp"
        try:
            file_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                existing_mode,
            )
            try:
                view = memoryview(encoded)
                while view:
                    written = os.write(file_fd, view)
                    if written <= 0:
                        raise PatchError("patch write made no progress")
                    view = view[written:]
                os.fsync(file_fd)
            finally:
                os.close(file_fd)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _read_changed_file(
        self, root_path: Path, path: str, expected: ManifestEntry
    ) -> bytes:
        if expected.size > self._max_file_bytes:
            raise PatchError(f"changed file exceeds diff byte limit: {path}")
        with SecureRoot(root_path) as root:
            file_fd, opened = root.open_regular_file(path)
            try:
                payload = bytearray()
                while chunk := os.read(file_fd, 128 * 1024):
                    payload.extend(chunk)
                final = os.fstat(file_fd)
            finally:
                os.close(file_fd)
        if (
            len(payload) != expected.size
            or hashlib.sha256(payload).hexdigest() != expected.sha256
            or bool(opened.st_mode & 0o111) != expected.executable
            or self._file_version(opened) != self._file_version(final)
        ):
            raise PatchError(f"changed file raced during diff read: {path}")
        return bytes(payload)

    @staticmethod
    def _open_export_destination(
        destination: Path, forbidden_roots: tuple[Path, ...]
    ) -> int:
        if not destination.name or destination.name in {".", ".."}:
            raise PatchError("export destination must name a new file")
        parent = destination.absolute().parent
        try:
            parent_fd = os.open(
                parent,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except OSError as error:
            raise PatchError(
                "export parent must be an existing safe directory"
            ) from error
        try:
            for forbidden in forbidden_roots:
                with SecureRoot(forbidden) as root:
                    root_fd = root.duplicate_root()
                    try:
                        root_stat = os.fstat(root_fd)
                    finally:
                        os.close(root_fd)
                    if WorkspaceEditor._directory_is_within(parent_fd, root_stat):
                        raise PatchError(
                            "export destination cannot be inside a protected root"
                        )
            file_fd = os.open(
                destination.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=parent_fd,
            )
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode):
                os.close(file_fd)
                raise PatchError("export destination is not a regular file")
            return file_fd
        except OSError as error:
            raise PatchError("export destination must be a new safe file") from error
        finally:
            os.close(parent_fd)

    @staticmethod
    def _directory_is_within(directory_fd: int, ancestor: os.stat_result) -> bool:
        current_fd = os.dup(directory_fd)
        try:
            while True:
                current = os.fstat(current_fd)
                if (current.st_dev, current.st_ino) == (
                    ancestor.st_dev,
                    ancestor.st_ino,
                ):
                    return True
                parent_fd = os.open(
                    "..",
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=current_fd,
                )
                parent = os.fstat(parent_fd)
                if (parent.st_dev, parent.st_ino) == (
                    current.st_dev,
                    current.st_ino,
                ):
                    os.close(parent_fd)
                    return False
                os.close(current_fd)
                current_fd = parent_fd
        finally:
            os.close(current_fd)

    @staticmethod
    def _file_version(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
        )

    @staticmethod
    def _remove_empty_parents(path: Path, root: Path) -> None:
        current = path
        while current != root:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent
