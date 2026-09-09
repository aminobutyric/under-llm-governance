# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ulg.audit.events import (
    ActionDecisionEvent,
    ApprovalRequestedEvent,
    ApprovalResolvedEvent,
    AuditEvent,
    GrantConsumedEvent,
    GrantIssuedEvent,
    GrantRejectedEvent,
    ModelFailureEvent,
    PatchExportedEvent,
    SandboxFinishedEvent,
    TaskLifecycleEvent,
    ToolFinishedEvent,
    WorkspaceDiscardedEvent,
    WorkspaceGenerationEvent,
)
from ulg.policy import DecisionKind

_MAX_AUDIT_BYTES = 16 * 1024 * 1024
_MAX_EVENT_BYTES = 65_536
_MAX_EVENTS = 10_000
_MAX_TIMELINE_EVENTS = 200
_AUDIT_ADAPTER: TypeAdapter[AuditEvent] = TypeAdapter(AuditEvent)


class AuditReadError(RuntimeError):
    """An audit file is unavailable, malformed, oversized, or unsafe."""


class AuditTimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    created_at: str
    event_type: str
    outcome: str | None = None
    action_type: str | None = None
    recipe_name: str | None = None
    generation: int | None = Field(default=None, ge=0)


class AuditSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: UUID
    status: str
    events_total: int = Field(ge=0)
    proposed_actions: int = Field(ge=0)
    approval_requests: int = Field(ge=0)
    approved_actions: int = Field(ge=0)
    denied_actions: int = Field(ge=0)
    executed_actions: int = Field(ge=0)
    successful_actions: int = Field(ge=0)
    sandbox_runs: int = Field(ge=0)
    verified_checks: int = Field(ge=0)
    failures: int = Field(ge=0)
    latest_generation: int = Field(ge=0)
    patch_exported: bool
    workspace_discarded: bool
    incomplete_tail: bool
    timeline_truncated: bool
    timeline: tuple[AuditTimelineEntry, ...]


def read_audit_summary(path: Path, *, task_id: UUID) -> AuditSummary:
    payload = _read_bounded_regular_file(path)
    incomplete_tail = bool(payload) and not payload.endswith(b"\n")
    lines = payload.splitlines()
    if incomplete_tail and lines:
        lines.pop()
    if len(lines) > _MAX_EVENTS:
        raise AuditReadError("audit event count exceeds review limit")

    events: list[AuditEvent] = []
    for line in lines:
        if not line:
            continue
        if len(line) > _MAX_EVENT_BYTES:
            raise AuditReadError("audit event exceeds review byte limit")
        try:
            event = _AUDIT_ADAPTER.validate_json(line)
        except ValueError as error:
            raise AuditReadError("audit file contains a malformed event") from error
        if event.task_id != task_id:
            raise AuditReadError("audit file contains an event for another task")
        events.append(event)

    return _summarize(events, task_id=task_id, incomplete_tail=incomplete_tail)


def _read_bounded_regular_file(path: Path) -> bytes:
    try:
        file_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as error:
        raise AuditReadError("audit file cannot be opened safely") from error
    try:
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise AuditReadError("audit path is not a regular file")
        payload = bytearray()
        while chunk := os.read(
            file_fd, min(131_072, _MAX_AUDIT_BYTES + 1 - len(payload))
        ):
            payload.extend(chunk)
            if len(payload) > _MAX_AUDIT_BYTES:
                raise AuditReadError("audit file exceeds review byte limit")
        final = os.fstat(file_fd)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
        ):
            raise AuditReadError("audit file changed while being read")
        return bytes(payload)
    finally:
        os.close(file_fd)


def _summarize(
    events: list[AuditEvent], *, task_id: UUID, incomplete_tail: bool
) -> AuditSummary:
    proposed = sum(isinstance(event, ActionDecisionEvent) for event in events)
    requests = sum(isinstance(event, ApprovalRequestedEvent) for event in events)
    approved = sum(
        isinstance(event, ApprovalResolvedEvent) and event.resolution != "deny"
        for event in events
    )
    denied = sum(
        isinstance(event, ApprovalResolvedEvent) and event.resolution == "deny"
        for event in events
    ) + sum(
        isinstance(event, ActionDecisionEvent) and event.decision is DecisionKind.DENY
        for event in events
    )
    tools = [event for event in events if isinstance(event, ToolFinishedEvent)]
    sandboxes = [event for event in events if isinstance(event, SandboxFinishedEvent)]
    failures = sum(not event.ok for event in tools) + sum(
        isinstance(event, ModelFailureEvent) and not event.retrying for event in events
    )
    generations = [
        event.generation
        for event in events
        if isinstance(event, (WorkspaceGenerationEvent, PatchExportedEvent))
    ]
    status = "unknown"
    for event in events:
        if isinstance(event, TaskLifecycleEvent):
            status = event.event_type.removeprefix("task_")
        elif isinstance(event, WorkspaceDiscardedEvent):
            status = "discarded"

    timeline_events = events[-_MAX_TIMELINE_EVENTS:]
    return AuditSummary(
        task_id=task_id,
        status=status,
        events_total=len(events),
        proposed_actions=proposed,
        approval_requests=requests,
        approved_actions=approved,
        denied_actions=denied,
        executed_actions=len(tools),
        successful_actions=sum(event.ok for event in tools),
        sandbox_runs=len(sandboxes),
        verified_checks=sum(event.ok for event in sandboxes),
        failures=failures,
        latest_generation=max(generations, default=0),
        patch_exported=any(isinstance(event, PatchExportedEvent) for event in events),
        workspace_discarded=any(
            isinstance(event, WorkspaceDiscardedEvent) for event in events
        ),
        incomplete_tail=incomplete_tail,
        timeline_truncated=len(events) > len(timeline_events),
        timeline=tuple(_timeline_entry(event) for event in timeline_events),
    )


def _timeline_entry(event: AuditEvent) -> AuditTimelineEntry:
    payload: dict[str, Any] = {
        "created_at": event.created_at.isoformat(),
        "event_type": event.event_type,
    }
    if isinstance(event, TaskLifecycleEvent):
        payload["outcome"] = event.reason_code or event.event_type.removeprefix("task_")
    elif isinstance(event, ActionDecisionEvent):
        payload.update(outcome=event.decision.value, action_type=event.action_type)
    elif isinstance(event, ApprovalRequestedEvent):
        payload.update(action_type=event.action_type, recipe_name=event.recipe_name)
    elif isinstance(event, ApprovalResolvedEvent):
        payload["outcome"] = event.resolution
    elif isinstance(event, (GrantIssuedEvent, GrantConsumedEvent)):
        payload["outcome"] = event.scope_type
    elif isinstance(event, GrantRejectedEvent):
        payload["outcome"] = event.reason_code
    elif isinstance(event, ToolFinishedEvent):
        payload.update(
            outcome="succeeded" if event.ok else event.error_code or "failed",
            action_type=event.action_type,
        )
    elif isinstance(event, ModelFailureEvent):
        payload["outcome"] = event.error_code
    elif isinstance(event, WorkspaceGenerationEvent):
        payload["generation"] = event.generation
    elif isinstance(event, SandboxFinishedEvent):
        payload.update(
            outcome="verified" if event.ok else event.error_code or "failed",
            recipe_name=event.recipe_name,
        )
    elif isinstance(event, PatchExportedEvent):
        payload.update(outcome="exported", generation=event.generation)
    elif isinstance(event, WorkspaceDiscardedEvent):
        payload.update(outcome=event.reason_code, generation=event.generation)
    return AuditTimelineEntry.model_validate(payload)
