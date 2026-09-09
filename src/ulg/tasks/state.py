# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ulg.actions import Action, ApplyPatchAction, RunTaskAction
from ulg.approval import GrantRecord, action_digest
from ulg.tools import ApplyPatchResult, ToolResult

_MAX_STATE_BYTES = 1_048_576
_MAX_TASK_TEXT_BYTES = 262_144


class TaskStateError(RuntimeError):
    """Durable task state is unavailable, malformed, stale, or unsafe."""


class TaskBusyError(TaskStateError):
    """Another process currently owns the task lease."""


class EffectReplayError(TaskStateError):
    """An already scheduled effect was presented for execution again."""


class TaskPhase(StrEnum):
    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"
    RETRY = "retry"
    CANCEL = "cancel"
    EXPORT = "export"
    DISCARD = "discard"


_TRANSITIONS: dict[TaskPhase, frozenset[TaskPhase]] = {
    TaskPhase.PLAN: frozenset({TaskPhase.EXECUTE, TaskPhase.CANCEL, TaskPhase.DISCARD}),
    TaskPhase.EXECUTE: frozenset(
        {TaskPhase.REVIEW, TaskPhase.RETRY, TaskPhase.CANCEL, TaskPhase.DISCARD}
    ),
    TaskPhase.REVIEW: frozenset(
        {TaskPhase.EXECUTE, TaskPhase.EXPORT, TaskPhase.RETRY, TaskPhase.DISCARD}
    ),
    TaskPhase.RETRY: frozenset(
        {TaskPhase.EXECUTE, TaskPhase.EXPORT, TaskPhase.CANCEL, TaskPhase.DISCARD}
    ),
    TaskPhase.CANCEL: frozenset(
        {TaskPhase.EXECUTE, TaskPhase.EXPORT, TaskPhase.DISCARD}
    ),
    TaskPhase.EXPORT: frozenset({TaskPhase.DISCARD}),
    TaskPhase.DISCARD: frozenset(),
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PendingEffect(_StrictModel):
    action_id: UUID
    action_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    action_type: Literal["apply_patch", "run_task"]
    generation_before: int = Field(ge=0)
    recipe_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("started_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("effect timestamp must be timezone-aware UTC")
        return value


class EffectOutcome(_StrictModel):
    action_id: UUID
    action_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    action_type: Literal["apply_patch", "run_task"]
    outcome: Literal["succeeded", "failed", "interrupted", "unknown"]
    generation_before: int = Field(ge=0)
    generation_after: int = Field(ge=0)
    recipe_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("recorded_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("effect timestamp must be timezone-aware UTC")
        return value


class TaskState(_StrictModel):
    schema_version: Literal[1] = 1
    revision: int = Field(ge=0, default=0)
    task_id: UUID
    phase: TaskPhase = TaskPhase.PLAN
    source_root: Path
    config_path: Path
    config_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    model_name: str = Field(min_length=1, max_length=200)
    task_text: str = Field(min_length=1, max_length=_MAX_TASK_TEXT_BYTES)
    output_path: Path
    failure_mode: Literal["retain", "recover"] = "retain"
    generation: int = Field(ge=0, default=0)
    pending_effect: PendingEffect | None = None
    effects: tuple[EffectOutcome, ...] = Field(default=(), max_length=1_000)
    last_error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("source_root", "config_path", "output_path")
    @classmethod
    def require_absolute_paths(cls, value: Path) -> Path:
        if not value.is_absolute() or "\x00" in str(value):
            raise ValueError("durable task paths must be absolute and NUL-free")
        return value

    @field_validator("task_text")
    @classmethod
    def bound_task_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > _MAX_TASK_TEXT_BYTES:
            raise ValueError("task text exceeds durable byte limit")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("task timestamps must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def validate_effects(self) -> TaskState:
        action_ids = tuple(effect.action_id for effect in self.effects)
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("completed effect identifiers must be unique")
        if (
            self.pending_effect is not None
            and self.pending_effect.action_id in action_ids
        ):
            raise ValueError("pending effect is already recorded as complete")
        return self


class GrantSnapshot(_StrictModel):
    schema_version: Literal[1] = 1
    task_id: UUID
    records: tuple[GrantRecord, ...] = ()

    @model_validator(mode="after")
    def validate_records(self) -> GrantSnapshot:
        identifiers = tuple(record.grant.grant_id for record in self.records)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("grant snapshot contains duplicate identifiers")
        if any(record.grant.task_id != self.task_id for record in self.records):
            raise ValueError("grant snapshot contains a different task")
        return self


class TaskStore:
    """Atomic, no-follow JSON task state beneath an application-owned directory."""

    def __init__(self, root: Path) -> None:
        self._root = root.absolute()

    def create(self, state: TaskState) -> None:
        self._prepare_root()
        path = self._state_path(state.task_id)
        if path.exists():
            raise TaskStateError("task state already exists")
        self._write_atomic(path, state.model_dump_json().encode("utf-8"))

    def load(self, task_id: UUID) -> TaskState:
        payload = self._read_bounded(self._state_path(task_id))
        try:
            return TaskState.model_validate_json(payload)
        except ValueError as error:
            raise TaskStateError("task state is malformed") from error

    def save(self, state: TaskState, *, expected_revision: int) -> None:
        current = self.load(state.task_id)
        if (
            current.revision != expected_revision
            or state.revision != expected_revision + 1
        ):
            raise TaskStateError("task state revision changed concurrently")
        self._write_atomic(
            self._state_path(state.task_id), state.model_dump_json().encode("utf-8")
        )

    def load_grants(self, task_id: UUID) -> tuple[GrantRecord, ...]:
        path = self._grant_path(task_id)
        if not path.exists():
            return ()
        payload = self._read_bounded(path)
        try:
            snapshot = GrantSnapshot.model_validate_json(payload)
        except ValueError as error:
            raise TaskStateError("grant state is malformed") from error
        if snapshot.task_id != task_id:
            raise TaskStateError("grant state belongs to a different task")
        return snapshot.records

    def save_grants(self, task_id: UUID, records: tuple[GrantRecord, ...]) -> None:
        snapshot = GrantSnapshot(task_id=task_id, records=records)
        self._write_atomic(
            self._grant_path(task_id), snapshot.model_dump_json().encode("utf-8")
        )

    def delete_grants(self, task_id: UUID) -> None:
        path = self._grant_path(task_id)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise TaskStateError("grant state path is unsafe")
        path.unlink()
        self._fsync_root()

    def delete_state(self, task_id: UUID, *, expected_revision: int) -> None:
        current = self.load(task_id)
        if current.revision != expected_revision:
            raise TaskStateError("task state revision changed concurrently")
        path = self._state_path(task_id)
        try:
            metadata = path.lstat()
        except OSError as error:
            raise TaskStateError("task state cannot be removed safely") from error
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise TaskStateError("task state path is unsafe")
        try:
            path.unlink()
            self._fsync_root()
        except OSError as error:
            raise TaskStateError("task state cannot be removed safely") from error

    def delete_idle_lock(self, task_id: UUID) -> None:
        """Remove a lock inode only when no process currently owns it."""

        path = self._lock_path(task_id)
        try:
            file_fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError:
            return
        except OSError as error:
            raise TaskStateError("task lease cannot be removed safely") from error
        try:
            try:
                fcntl.flock(file_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise TaskBusyError("task is active during cleanup") from error
            opened = os.fstat(file_fd)
            current = path.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or path.is_symlink()
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise TaskStateError("task lease path changed during cleanup")
            path.unlink()
            self._fsync_root()
        except OSError as error:
            raise TaskStateError("task lease cannot be removed safely") from error
        finally:
            os.close(file_fd)

    @contextmanager
    def lease(self, task_id: UUID) -> Iterator[TaskSession]:
        self._prepare_root()
        lock_path = self._lock_path(task_id)
        try:
            file_fd = os.open(
                lock_path,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
            )
        except OSError as error:
            raise TaskStateError("task lease cannot be opened safely") from error
        try:
            try:
                fcntl.flock(file_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise TaskBusyError(
                    "task is already active in another process"
                ) from error
            yield TaskSession(store=self, state=self.load(task_id))
        finally:
            os.close(file_fd)

    def _prepare_root(self) -> None:
        try:
            self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
            metadata = self._root.lstat()
        except OSError as error:
            raise TaskStateError("task state root is unavailable") from error
        if not stat.S_ISDIR(metadata.st_mode) or self._root.is_symlink():
            raise TaskStateError("task state root must be a real directory")
        os.chmod(self._root, 0o700)

    def _state_path(self, task_id: UUID) -> Path:
        return self._root / f"{task_id.hex}.json"

    def _grant_path(self, task_id: UUID) -> Path:
        return self._root / f"{task_id.hex}.grants.json"

    def _lock_path(self, task_id: UUID) -> Path:
        return self._root / f"{task_id.hex}.lock"

    def _write_atomic(self, path: Path, payload: bytes) -> None:
        self._prepare_root()
        if len(payload) > _MAX_STATE_BYTES:
            raise TaskStateError("durable state exceeds byte limit")
        temporary = self._root / f".{path.name}.{uuid4().hex}.tmp"
        file_fd = -1
        try:
            file_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
            )
            view = memoryview(payload)
            while view:
                written = os.write(file_fd, view)
                if written <= 0:
                    raise TaskStateError("durable state write made no progress")
                view = view[written:]
            os.fsync(file_fd)
            os.close(file_fd)
            file_fd = -1
            os.replace(temporary, path)
            self._fsync_root()
        except OSError as error:
            raise TaskStateError("durable state cannot be committed safely") from error
        finally:
            if file_fd >= 0:
                os.close(file_fd)
            temporary.unlink(missing_ok=True)

    def _read_bounded(self, path: Path) -> bytes:
        try:
            file_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError as error:
            raise TaskStateError("durable state cannot be opened safely") from error
        try:
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode):
                raise TaskStateError("durable state is not a regular file")
            payload = bytearray()
            while chunk := os.read(
                file_fd, min(131_072, _MAX_STATE_BYTES + 1 - len(payload))
            ):
                payload.extend(chunk)
                if len(payload) > _MAX_STATE_BYTES:
                    raise TaskStateError("durable state exceeds byte limit")
            final = os.fstat(file_fd)
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                final.st_dev,
                final.st_ino,
                final.st_size,
                final.st_mtime_ns,
            ):
                raise TaskStateError("durable state changed while being read")
            return bytes(payload)
        finally:
            os.close(file_fd)

    def _fsync_root(self) -> None:
        directory_fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


class TaskSession:
    """Mutable handle whose every update becomes one atomic state revision."""

    def __init__(self, *, store: TaskStore, state: TaskState) -> None:
        self._store = store
        self.state = state

    def update(self, **changes: object) -> TaskState:
        payload = self.state.model_dump()
        payload.update(changes)
        payload["revision"] = self.state.revision + 1
        payload["updated_at"] = datetime.now(UTC)
        candidate = TaskState.model_validate(payload)
        self._store.save(candidate, expected_revision=self.state.revision)
        self.state = candidate
        return candidate

    def transition(self, phase: TaskPhase, **changes: object) -> TaskState:
        current = self.state.phase
        if phase != current and phase not in _TRANSITIONS[current]:
            raise TaskStateError(f"invalid task transition: {current} -> {phase}")
        return self.update(phase=phase, **changes)


class DurableEffectJournal:
    """Persist at-most-once effect scheduling around controller tool execution."""

    def __init__(self, session: TaskSession) -> None:
        self._session = session

    def before_execute(self, action: Action) -> None:
        if not isinstance(action, (ApplyPatchAction, RunTaskAction)):
            return
        state = self._session.state
        if any(effect.action_id == action.action_id for effect in state.effects):
            raise EffectReplayError("effect action was already scheduled")
        if state.pending_effect is not None:
            raise EffectReplayError("another effect has an unresolved outcome")
        pending = PendingEffect(
            action_id=action.action_id,
            action_digest=action_digest(action),
            action_type=action.type,
            generation_before=state.generation,
            recipe_name=(
                action.recipe_name if isinstance(action, RunTaskAction) else None
            ),
        )
        self._session.transition(TaskPhase.EXECUTE, pending_effect=pending)

    def after_execute(self, action: Action, result: ToolResult) -> None:
        if not isinstance(action, (ApplyPatchAction, RunTaskAction)):
            return
        state = self._session.state
        pending = state.pending_effect
        if pending is None or pending.action_id != action.action_id:
            raise TaskStateError("effect completion does not match durable schedule")
        generation = state.generation
        if isinstance(result, ApplyPatchResult) and result.ok:
            generation = result.generation
        effect = EffectOutcome(
            action_id=pending.action_id,
            action_digest=pending.action_digest,
            action_type=pending.action_type,
            outcome="succeeded" if result.ok else "failed",
            generation_before=pending.generation_before,
            generation_after=generation,
            recipe_name=pending.recipe_name,
        )
        phase = TaskPhase.REVIEW if generation > 0 else TaskPhase.EXECUTE
        self._session.transition(
            phase,
            generation=generation,
            pending_effect=None,
            effects=(*state.effects, effect),
        )

    def reconcile(self, *, recovered_generation: int) -> PendingEffect | None:
        state = self._session.state
        pending = state.pending_effect
        if pending is None:
            if recovered_generation != state.generation:
                self._session.update(generation=recovered_generation)
            return None
        if pending.action_type == "apply_patch":
            outcome: Literal["succeeded", "interrupted", "unknown"] = (
                "succeeded"
                if recovered_generation > pending.generation_before
                else "interrupted"
            )
        else:
            outcome = "unknown"
        effect = EffectOutcome(
            action_id=pending.action_id,
            action_digest=pending.action_digest,
            action_type=pending.action_type,
            outcome=outcome,
            generation_before=pending.generation_before,
            generation_after=recovered_generation,
            recipe_name=pending.recipe_name,
        )
        phase = TaskPhase.REVIEW if outcome == "succeeded" else TaskPhase.RETRY
        self._session.transition(
            phase,
            generation=recovered_generation,
            pending_effect=None,
            effects=(*state.effects, effect),
            last_error_code=(
                None if outcome == "succeeded" else "effect_outcome_unknown"
            ),
        )
        return pending
