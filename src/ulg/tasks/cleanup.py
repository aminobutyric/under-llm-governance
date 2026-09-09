# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ulg.tasks.state import TaskState, TaskStateError


class CleanupCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: UUID
    phase: str
    revision: int = Field(ge=0)
    updated_at: datetime
    age_seconds: int = Field(ge=0)
    bytes_total: int = Field(ge=0)
    retained: bool


def inspect_cleanup_candidate(state_root: Path, state: TaskState) -> CleanupCandidate:
    size = sum(_path_size(path) for path in _artifact_paths(state_root, state.task_id))
    age = max(0, int((datetime.now(UTC) - state.updated_at).total_seconds()))
    return CleanupCandidate(
        task_id=state.task_id,
        phase=state.phase.value,
        revision=state.revision,
        updated_at=state.updated_at,
        age_seconds=age,
        bytes_total=size,
        retained=state.phase.value != "discard",
    )


def remove_task_artifacts(state_root: Path, task_id: UUID) -> None:
    _remove_directory(state_root / "workspaces" / task_id.hex)
    _remove_regular_file(state_root / "audit" / f"{task_id}.jsonl")


def _artifact_paths(state_root: Path, task_id: UUID) -> tuple[Path, ...]:
    return (
        state_root / "workspaces" / task_id.hex,
        state_root / "audit" / f"{task_id}.jsonl",
        state_root / "tasks" / f"{task_id.hex}.json",
        state_root / "tasks" / f"{task_id.hex}.grants.json",
    )


def _path_size(path: Path) -> int:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return 0
    except OSError as error:
        raise TaskStateError("task artifact cannot be inspected safely") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise TaskStateError("task artifact path is a symbolic link")
    if stat.S_ISREG(metadata.st_mode):
        return metadata.st_size
    if not stat.S_ISDIR(metadata.st_mode):
        raise TaskStateError("task artifact has an unsupported file type")
    total = metadata.st_size
    try:
        for root, directory_names, file_names in os.walk(path, followlinks=False):
            root_path = Path(root)
            for name in (*directory_names, *file_names):
                total += (root_path / name).lstat().st_size
    except OSError as error:
        raise TaskStateError("task artifact cannot be measured safely") from error
    return total


def _remove_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise TaskStateError("task workspace cannot be removed safely") from error
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise TaskStateError("task workspace path is unsafe")
    try:
        for root, directory_names, _ in os.walk(path, followlinks=False):
            root_path = Path(root)
            root_path.chmod(0o700)
            for name in directory_names:
                child = root_path / name
                if not child.is_symlink():
                    child.chmod(0o700)
        shutil.rmtree(path)
    except OSError as error:
        raise TaskStateError("task workspace cannot be removed safely") from error


def _remove_regular_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise TaskStateError("task audit cannot be removed safely") from error
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise TaskStateError("task audit path is unsafe")
    try:
        path.unlink()
    except OSError as error:
        raise TaskStateError("task audit cannot be removed safely") from error
