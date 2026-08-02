# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ulg.workspace.paths import PathSecurityError, SecureRoot, relative_parts

_READ_CHUNK_BYTES = 128 * 1024


class ManifestError(RuntimeError):
    """A generation manifest was missing, malformed, stale, or unsafe."""


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: str = Field(min_length=1, max_length=4096)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    executable: bool

    @field_validator("path")
    @classmethod
    def require_contained_file_path(cls, value: str) -> str:
        try:
            parts = relative_parts(value)
        except PathSecurityError as error:
            raise ValueError("manifest path must remain relative") from error
        if not parts:
            raise ValueError("manifest path must name a file")
        normalized = "/".join(parts)
        if normalized != value:
            raise ValueError("manifest path must be normalized")
        return value


class GenerationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    task_id: UUID
    generation: int = Field(ge=0)
    parent_tree_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    entries: tuple[ManifestEntry, ...]
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_summary(self) -> GenerationManifest:
        paths = tuple(entry.path for entry in self.entries)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("manifest entries must have unique sorted paths")
        if self.file_count != len(self.entries):
            raise ValueError("manifest file count does not match entries")
        if self.total_bytes != sum(entry.size for entry in self.entries):
            raise ValueError("manifest byte total does not match entries")
        if self.tree_sha256 != tree_digest(self.entries):
            raise ValueError("manifest tree digest does not match entries")
        if self.generation == 0 and self.parent_tree_sha256 is not None:
            raise ValueError("source generation cannot name a parent tree")
        if self.generation > 0 and self.parent_tree_sha256 is None:
            raise ValueError("derived generation must name its parent tree")
        return self


def tree_digest(entries: tuple[ManifestEntry, ...]) -> str:
    payload = json.dumps(
        [entry.model_dump(mode="json") for entry in entries],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_manifest(
    *,
    task_id: UUID,
    generation: int,
    entries: tuple[ManifestEntry, ...],
    parent_tree_sha256: str | None = None,
) -> GenerationManifest:
    ordered = tuple(sorted(entries, key=lambda entry: entry.path))
    return GenerationManifest(
        task_id=task_id,
        generation=generation,
        parent_tree_sha256=parent_tree_sha256,
        entries=ordered,
        file_count=len(ordered),
        total_bytes=sum(entry.size for entry in ordered),
        tree_sha256=tree_digest(ordered),
    )


def scan_generation(
    root_path: Path,
    *,
    task_id: UUID,
    generation: int,
    parent_tree_sha256: str | None,
    max_files: int,
    max_bytes: int,
) -> GenerationManifest:
    entries: list[ManifestEntry] = []
    used_bytes = [0]
    with SecureRoot(root_path) as root:
        _scan_directory(
            root,
            root.duplicate_root(),
            PurePosixPath("."),
            entries,
            max_files=max_files,
            max_bytes=max_bytes,
            used_bytes=used_bytes,
        )
    return build_manifest(
        task_id=task_id,
        generation=generation,
        entries=tuple(entries),
        parent_tree_sha256=parent_tree_sha256,
    )


def _scan_directory(
    root: SecureRoot,
    directory_fd: int,
    relative: PurePosixPath,
    entries: list[ManifestEntry],
    *,
    max_files: int,
    max_bytes: int,
    used_bytes: list[int],
) -> None:
    try:
        try:
            names = sorted(os.listdir(directory_fd))
        except OSError as error:
            raise ManifestError("generation changed during manifest listing") from error
        for name in names:
            path = PurePosixPath(name) if str(relative) == "." else relative / name
            try:
                listed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as error:
                raise ManifestError(
                    "generation changed during manifest scan"
                ) from error
            if stat.S_ISDIR(listed.st_mode):
                child_fd = root.open_child_directory(directory_fd, name)
                _scan_directory(
                    root,
                    child_fd,
                    path,
                    entries,
                    max_files=max_files,
                    max_bytes=max_bytes,
                    used_bytes=used_bytes,
                )
                continue
            if not stat.S_ISREG(listed.st_mode) or listed.st_dev != root.device:
                raise ManifestError("generation contains an unsafe entry")
            file_fd, opened = root.open_regular_file(path.as_posix())
            try:
                digest = hashlib.sha256()
                while chunk := os.read(file_fd, _READ_CHUNK_BYTES):
                    digest.update(chunk)
                final = os.fstat(file_fd)
            finally:
                os.close(file_fd)
            if _file_version(opened) != _file_version(final):
                raise ManifestError("generation file changed during manifest scan")
            entries.append(
                ManifestEntry(
                    path=path.as_posix(),
                    size=opened.st_size,
                    sha256=digest.hexdigest(),
                    executable=bool(opened.st_mode & 0o111),
                )
            )
            if len(entries) > max_files:
                raise ManifestError("generation exceeds file-count quota")
            used_bytes[0] += opened.st_size
            if used_bytes[0] > max_bytes:
                raise ManifestError("generation exceeds byte quota")
    finally:
        os.close(directory_fd)


def _file_version(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )
