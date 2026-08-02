# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from pathspec import GitIgnoreSpec

from ulg.config.models import WorkspaceSettings
from ulg.workspace.base import WorkspaceRef
from ulg.workspace.exclusions import ExclusionPolicy, ScopedGitIgnore
from ulg.workspace.manifests import (
    GenerationManifest,
    ManifestEntry,
    ManifestError,
    build_manifest,
    scan_generation,
)
from ulg.workspace.paths import PathSecurityError, SecureRoot

_COPY_CHUNK_BYTES = 128 * 1024
_MAX_GITIGNORE_BYTES = 1024 * 1024
_ROOT_RELATIVE = PurePosixPath(".")


class SnapshotError(RuntimeError):
    """A source directory could not be copied without weakening containment."""


@dataclass
class _CopyBudget:
    limit: int
    used: int = 0

    def consume(self, amount: int) -> None:
        self.used += amount
        if self.used > self.limit:
            raise SnapshotError("workspace exceeds configured byte quota")


@dataclass(frozen=True)
class _GitIgnoreFile:
    rule: ScopedGitIgnore
    payload: bytes
    executable: bool


class SnapshotWorkspaceManager:
    """Create generation zero without ever opening a writable source handle."""

    def __init__(self, state_root: Path, settings: WorkspaceSettings) -> None:
        self._state_root = state_root.absolute()
        self._settings = settings
        self._policy = ExclusionPolicy(settings.exclude)

    @property
    def exclusion_policy(self) -> ExclusionPolicy:
        return self._policy

    @property
    def max_bytes(self) -> int:
        return self._settings.max_bytes

    @property
    def max_generations(self) -> int:
        return self._settings.max_generations

    @property
    def max_files(self) -> int:
        return self._settings.max_files

    def create(self, *, source: Path, task_id: UUID) -> WorkspaceRef:
        self._refuse_state_inside_source(source)
        self._prepare_state_root()
        task_root = self._state_root / task_id.hex
        generation_root = task_root / "generation-0"
        try:
            task_root.mkdir(mode=0o700)
            generation_root.mkdir(mode=0o700)
            copied_entries: list[ManifestEntry] = []
            with SecureRoot(source) as secure_source:
                source_fd = secure_source.duplicate_root()
                try:
                    self._copy_directory(
                        secure_source,
                        source_fd,
                        generation_root,
                        PurePosixPath("."),
                        (),
                        _CopyBudget(self._settings.max_bytes),
                        copied_entries,
                    )
                finally:
                    os.close(source_fd)
            expected = build_manifest(
                task_id=task_id,
                generation=0,
                entries=tuple(copied_entries),
            )
            actual = self._scan_manifest(
                WorkspaceRef(task_id=task_id, root=generation_root, generation=0),
                parent_tree_sha256=None,
            )
            if actual != expected:
                raise SnapshotError("workspace copy does not match its source manifest")
            self.write_manifest(actual)
        except (
            OSError,
            PathSecurityError,
            UnicodeError,
            ManifestError,
            SnapshotError,
        ) as error:
            if task_root.parent == self._state_root and task_root.exists():
                shutil.rmtree(task_root)
            if isinstance(error, SnapshotError):
                raise
            raise SnapshotError("failed to create a safe workspace snapshot") from error
        return WorkspaceRef(task_id=task_id, root=generation_root, generation=0)

    def discard(self, workspace: WorkspaceRef) -> None:
        task_root = workspace.root.parent
        if (
            task_root.parent != self._state_root
            or task_root.name != workspace.task_id.hex
            or workspace.root.name != f"generation-{workspace.generation}"
        ):
            raise SnapshotError("refusing to discard an unowned workspace path")
        if task_root.exists():
            shutil.rmtree(task_root)

    def copy_generation(
        self,
        workspace: WorkspaceRef,
        destination: Path,
        *,
        generation: int,
    ) -> GenerationManifest:
        """Copy and verify a complete generation into empty staging."""

        source_manifest = self.read_manifest(workspace, verify=True)
        destination.mkdir(mode=0o700)
        try:
            copied_entries: list[ManifestEntry] = []
            with SecureRoot(workspace.root) as source:
                source_fd = source.duplicate_root()
                try:
                    self._copy_existing_directory(
                        source,
                        source_fd,
                        destination,
                        _CopyBudget(self._settings.max_bytes),
                        copied_entries,
                    )
                finally:
                    os.close(source_fd)
            copied = build_manifest(
                task_id=workspace.task_id,
                generation=generation,
                entries=tuple(copied_entries),
                parent_tree_sha256=source_manifest.tree_sha256,
            )
            actual = scan_generation(
                destination,
                task_id=workspace.task_id,
                generation=generation,
                parent_tree_sha256=source_manifest.tree_sha256,
                max_files=self._settings.max_files,
                max_bytes=self._settings.max_bytes,
            )
            if actual != copied or actual.entries != source_manifest.entries:
                raise SnapshotError("generation copy does not match its manifest")
            return actual
        except BaseException:
            if destination.exists():
                shutil.rmtree(destination)
            raise

    def read_manifest(
        self, workspace: WorkspaceRef, *, verify: bool = False
    ) -> GenerationManifest:
        self._validate_workspace_ref(workspace)
        manifest_path = self._manifest_path(workspace)
        try:
            file_fd = os.open(
                manifest_path,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except OSError as error:
            raise SnapshotError("generation manifest is unavailable") from error
        try:
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode):
                raise SnapshotError("generation manifest is not a regular file")
            payload = self._read_bounded(file_fd, self._settings.max_manifest_bytes)
            final = os.fstat(file_fd)
            if self._file_version(opened) != self._file_version(final):
                raise SnapshotError("generation manifest changed while being read")
        finally:
            os.close(file_fd)
        try:
            manifest = GenerationManifest.model_validate_json(payload)
        except ValueError as error:
            raise SnapshotError("generation manifest is malformed") from error
        if (
            manifest.task_id != workspace.task_id
            or manifest.generation != workspace.generation
        ):
            raise SnapshotError("generation manifest identity does not match")
        if verify:
            actual = self._scan_manifest(
                workspace,
                parent_tree_sha256=manifest.parent_tree_sha256,
            )
            if actual != manifest:
                raise SnapshotError("generation no longer matches its manifest")
        return manifest

    def write_manifest(self, manifest: GenerationManifest) -> None:
        workspace = WorkspaceRef(
            task_id=manifest.task_id,
            root=(
                self._state_root
                / manifest.task_id.hex
                / f"generation-{manifest.generation}"
            ),
            generation=manifest.generation,
        )
        self._validate_workspace_ref(workspace)
        payload = manifest.model_dump_json().encode("utf-8")
        if len(payload) > self._settings.max_manifest_bytes:
            raise SnapshotError("generation manifest exceeds byte limit")
        path = self._manifest_path(workspace)
        created = False
        try:
            file_fd = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o400,
            )
            created = True
        except OSError as error:
            raise SnapshotError(
                "generation manifest cannot be created safely"
            ) from error
        try:
            view = memoryview(payload)
            while view:
                written = os.write(file_fd, view)
                if written <= 0:
                    raise SnapshotError("generation manifest write made no progress")
                view = view[written:]
            os.fsync(file_fd)
        except BaseException:
            if created:
                path.unlink(missing_ok=True)
            raise
        finally:
            os.close(file_fd)

    def scan_manifest(
        self,
        workspace: WorkspaceRef,
        *,
        parent_tree_sha256: str | None,
    ) -> GenerationManifest:
        self._validate_workspace_ref(workspace)
        return self._scan_manifest(
            workspace,
            parent_tree_sha256=parent_tree_sha256,
        )

    def scan_staging_manifest(
        self,
        workspace: WorkspaceRef,
        staging_root: Path,
        *,
        generation: int,
        parent_tree_sha256: str,
    ) -> GenerationManifest:
        self._validate_workspace_ref(workspace)
        expected = workspace.root.parent / f"generation-{generation}.staging"
        if staging_root != expected or generation != workspace.generation + 1:
            raise SnapshotError("staging generation is not the exact successor")
        return scan_generation(
            staging_root,
            task_id=workspace.task_id,
            generation=generation,
            parent_tree_sha256=parent_tree_sha256,
            max_files=self._settings.max_files,
            max_bytes=self._settings.max_bytes,
        )

    def remove_incomplete_next_generation(self, workspace: WorkspaceRef) -> None:
        """Remove only the exact unpublished successor left by an interruption."""

        self._validate_workspace_ref(workspace)
        next_generation = workspace.generation + 1
        for suffix in (".staging", ""):
            candidate = workspace.root.parent / f"generation-{next_generation}{suffix}"
            manifest = workspace.root.parent / f"manifest-{next_generation}.json"
            if not candidate.exists():
                continue
            candidate_stat = candidate.lstat()
            if not stat.S_ISDIR(candidate_stat.st_mode) or candidate.is_symlink():
                raise SnapshotError("incomplete generation path is unsafe")
            if suffix == "" and manifest.exists():
                raise SnapshotError("next complete generation already exists")
            shutil.rmtree(candidate)

    def _prepare_state_root(self) -> None:
        self._state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root_stat = self._state_root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode) or self._state_root.is_symlink():
            raise SnapshotError("state root must be a real directory")

    def _refuse_state_inside_source(self, source: Path) -> None:
        try:
            source_root = source.resolve(strict=True)
            state_root = self._state_root.resolve(strict=False)
        except OSError as error:
            raise SnapshotError(
                "cannot validate workspace and state separation"
            ) from error
        if state_root == source_root or state_root.is_relative_to(source_root):
            raise SnapshotError(
                "application state cannot be inside the source workspace"
            )

    def _validate_workspace_ref(self, workspace: WorkspaceRef) -> None:
        task_root = workspace.root.parent
        if (
            task_root.parent != self._state_root
            or task_root.name != workspace.task_id.hex
            or workspace.root.name != f"generation-{workspace.generation}"
        ):
            raise SnapshotError("workspace reference is not application-owned")

    @staticmethod
    def _manifest_path(workspace: WorkspaceRef) -> Path:
        return workspace.root.parent / f"manifest-{workspace.generation}.json"

    def _scan_manifest(
        self,
        workspace: WorkspaceRef,
        *,
        parent_tree_sha256: str | None,
    ) -> GenerationManifest:
        return scan_generation(
            workspace.root,
            task_id=workspace.task_id,
            generation=workspace.generation,
            parent_tree_sha256=parent_tree_sha256,
            max_files=self._settings.max_files,
            max_bytes=self._settings.max_bytes,
        )

    def _copy_directory(
        self,
        source: SecureRoot,
        source_fd: int,
        destination: Path,
        relative: PurePosixPath,
        inherited_rules: tuple[ScopedGitIgnore, ...],
        budget: _CopyBudget,
        entries: list[ManifestEntry],
    ) -> None:
        rules = inherited_rules
        gitignore: _GitIgnoreFile | None = None
        if self._settings.respect_gitignore:
            gitignore = self._read_gitignore(source_fd, relative)
            if gitignore is not None:
                rules = (*rules, gitignore.rule)

        try:
            names = sorted(os.listdir(source_fd))
        except OSError as error:
            raise SnapshotError("source directory changed during listing") from error

        for name in names:
            child_relative = relative / name
            display_relative = (
                PurePosixPath(name) if str(relative) == "." else child_relative
            )
            if name == ".gitignore" and self._settings.respect_gitignore:
                if gitignore is None:
                    raise SnapshotError(".gitignore appeared during snapshot creation")
                if not self._policy.is_permanently_excluded(
                    display_relative, is_directory=False
                ) and not self._policy.is_gitignored(
                    display_relative,
                    is_directory=False,
                    rules=rules,
                ):
                    budget.consume(len(gitignore.payload))
                    destination_path = destination / name
                    with destination_path.open("xb") as output:
                        output.write(gitignore.payload)
                    os.chmod(
                        destination_path,
                        0o700 if gitignore.executable else 0o600,
                    )
                    entries.append(
                        ManifestEntry(
                            path=display_relative.as_posix(),
                            size=len(gitignore.payload),
                            sha256=hashlib.sha256(gitignore.payload).hexdigest(),
                            executable=gitignore.executable,
                        )
                    )
                    self._enforce_file_count(entries)
                continue
            try:
                entry_stat = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
            except OSError as error:
                raise SnapshotError("source entry changed before inspection") from error
            is_directory = stat.S_ISDIR(entry_stat.st_mode)
            if self._policy.is_permanently_excluded(
                display_relative, is_directory=is_directory
            ) or self._policy.is_gitignored(
                display_relative,
                is_directory=is_directory,
                rules=rules,
            ):
                continue
            if stat.S_ISLNK(entry_stat.st_mode):
                raise SnapshotError("source contains a non-excluded symbolic link")
            destination_path = destination / name
            if is_directory:
                child_fd = source.open_child_directory(source_fd, name)
                try:
                    destination_path.mkdir(mode=0o700)
                    self._copy_directory(
                        source,
                        child_fd,
                        destination_path,
                        display_relative,
                        rules,
                        budget,
                        entries,
                    )
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(entry_stat.st_mode):
                self._copy_regular_file(
                    source,
                    source_fd,
                    name,
                    entry_stat,
                    destination_path,
                    budget,
                    display_relative,
                    entries,
                )
            else:
                raise SnapshotError("source contains a non-excluded special file")

    def _copy_existing_directory(
        self,
        source: SecureRoot,
        source_fd: int,
        destination: Path,
        budget: _CopyBudget,
        entries: list[ManifestEntry],
        relative: PurePosixPath = _ROOT_RELATIVE,
    ) -> None:
        try:
            names = sorted(os.listdir(source_fd))
        except OSError as error:
            raise SnapshotError("generation changed during listing") from error
        for name in names:
            try:
                entry_stat = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
            except OSError as error:
                raise SnapshotError("generation entry changed during copy") from error
            destination_path = destination / name
            display_relative = (
                PurePosixPath(name) if str(relative) == "." else relative / name
            )
            if stat.S_ISDIR(entry_stat.st_mode):
                child_fd = source.open_child_directory(source_fd, name)
                try:
                    destination_path.mkdir(mode=0o700)
                    self._copy_existing_directory(
                        source,
                        child_fd,
                        destination_path,
                        budget,
                        entries,
                        display_relative,
                    )
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(entry_stat.st_mode):
                self._copy_regular_file(
                    source,
                    source_fd,
                    name,
                    entry_stat,
                    destination_path,
                    budget,
                    display_relative,
                    entries,
                )
            else:
                raise SnapshotError("generation contains a special file or symlink")

    def _read_gitignore(
        self, directory_fd: int, relative: PurePosixPath
    ) -> _GitIgnoreFile | None:
        try:
            entry_stat = os.stat(
                ".gitignore", dir_fd=directory_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            return None
        except OSError as error:
            raise SnapshotError("cannot safely inspect .gitignore") from error
        if (
            not stat.S_ISREG(entry_stat.st_mode)
            or entry_stat.st_size > _MAX_GITIGNORE_BYTES
        ):
            raise SnapshotError(".gitignore must be a bounded regular file")
        try:
            file_fd = os.open(
                ".gitignore",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
        except OSError as error:
            raise SnapshotError("cannot safely open .gitignore") from error
        try:
            opened_stat = os.fstat(file_fd)
            if self._file_identity(entry_stat) != self._file_identity(opened_stat):
                raise SnapshotError(".gitignore changed identity during open")
            payload = self._read_bounded(file_fd, _MAX_GITIGNORE_BYTES)
            final_stat = os.fstat(file_fd)
            if self._file_version(opened_stat) != self._file_version(final_stat):
                raise SnapshotError(".gitignore changed while being read")
        finally:
            os.close(file_fd)
        base = PurePosixPath(".") if str(relative) == "." else relative
        return _GitIgnoreFile(
            rule=ScopedGitIgnore(
                base=base,
                spec=GitIgnoreSpec.from_lines(payload.decode("utf-8").splitlines()),
            ),
            payload=payload,
            executable=bool(opened_stat.st_mode & 0o111),
        )

    def _copy_regular_file(
        self,
        source: SecureRoot,
        directory_fd: int,
        name: str,
        listed_stat: os.stat_result,
        destination: Path,
        budget: _CopyBudget,
        relative: PurePosixPath,
        entries: list[ManifestEntry],
    ) -> None:
        try:
            file_fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
        except OSError as error:
            raise SnapshotError("source file cannot be opened safely") from error
        try:
            opened_stat = os.fstat(file_fd)
            if (
                self._file_identity(listed_stat) != self._file_identity(opened_stat)
                or not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_dev != source.device
            ):
                raise SnapshotError("source file changed identity during open")
            mode = 0o700 if opened_stat.st_mode & 0o111 else 0o600
            digest = hashlib.sha256()
            try:
                with destination.open("xb") as output:
                    os.chmod(destination, mode)
                    while chunk := os.read(file_fd, _COPY_CHUNK_BYTES):
                        budget.consume(len(chunk))
                        digest.update(chunk)
                        output.write(chunk)
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
            final_stat = os.fstat(file_fd)
            if self._file_version(opened_stat) != self._file_version(final_stat):
                destination.unlink(missing_ok=True)
                raise SnapshotError("source file changed while being copied")
            entries.append(
                ManifestEntry(
                    path=relative.as_posix(),
                    size=opened_stat.st_size,
                    sha256=digest.hexdigest(),
                    executable=bool(opened_stat.st_mode & 0o111),
                )
            )
            self._enforce_file_count(entries)
        finally:
            os.close(file_fd)

    @staticmethod
    def _read_bounded(file_fd: int, limit: int) -> bytes:
        payload = bytearray()
        while chunk := os.read(
            file_fd, min(_COPY_CHUNK_BYTES, limit + 1 - len(payload))
        ):
            payload.extend(chunk)
            if len(payload) > limit:
                raise SnapshotError("policy file exceeds its byte limit")
        return bytes(payload)

    @staticmethod
    def _file_identity(value: os.stat_result) -> tuple[int, int, int]:
        return (value.st_dev, value.st_ino, value.st_mode)

    @staticmethod
    def _file_version(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
        )

    def _enforce_file_count(self, entries: list[ManifestEntry]) -> None:
        if len(entries) > self._settings.max_files:
            raise SnapshotError("workspace exceeds configured file-count quota")
