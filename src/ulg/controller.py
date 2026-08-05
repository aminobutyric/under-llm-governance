# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import json
import time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ulg.actions import CompleteAction
from ulg.audit import (
    ActionDecisionEvent,
    AuditSink,
    ModelFailureEvent,
    SandboxFinishedEvent,
    TaskLifecycleEvent,
    ToolFinishedEvent,
    WorkspaceGenerationEvent,
)
from ulg.config.models import TaskSettings
from ulg.model import ChatMessage, ModelAdapter, ModelProtocolError
from ulg.policy import Decision, DecisionKind
from ulg.policy.engine import PolicyEngine
from ulg.tools import ApplyPatchResult, ReadFileResult, RunTaskResult, ToolRunner


class ControllerLimitError(RuntimeError):
    """The task stopped at a configured controller limit."""


class DryRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: UUID
    action_type: str
    decision: DecisionKind
    executed: bool


class InspectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: UUID
    status: str = Field(pattern=r"^completed$")
    model_summary: str
    turns: int = Field(gt=0)
    tool_calls: int = Field(ge=0)
    denied_actions: int = Field(ge=0)
    model_failures: int = Field(ge=0)
    files_read: tuple[str, ...]
    changed_files: tuple[str, ...] = ()
    generation: int = Field(ge=0, default=0)


class Controller:
    """Trusted Phase 0 contract path; intentionally executes no tools."""

    def __init__(
        self,
        *,
        model: ModelAdapter,
        policy: PolicyEngine,
        audit: AuditSink,
    ) -> None:
        self._model = model
        self._policy = policy
        self._audit = audit

    def dry_run_once(self, *, task_id: UUID, prompt: str) -> DryRunResult:
        action = self._model.propose(
            task_id=task_id,
            messages=[ChatMessage(role="user", content=prompt)],
        )
        decision: Decision = self._policy.evaluate(action)
        self._audit.append(
            ActionDecisionEvent(
                task_id=task_id,
                action_id=action.action_id,
                action_type=action.type,
                decision=decision.kind,
                reason_code=decision.reason_code,
                executed=False,
            )
        )
        return DryRunResult(
            task_id=task_id,
            action_type=action.type,
            decision=decision.kind,
            executed=False,
        )


class ReadOnlyController:
    """Bounded model/tool loop for the read-only inspection phase."""

    def __init__(
        self,
        *,
        model: ModelAdapter,
        policy: PolicyEngine,
        tools: ToolRunner,
        audit: AuditSink,
        settings: TaskSettings,
    ) -> None:
        self._model = model
        self._policy = policy
        self._tools = tools
        self._audit = audit
        self._settings = settings

    def run(self, *, task_id: UUID, task: str) -> InspectionReport:
        messages = [ChatMessage(role="user", content=task)]
        self._check_context(messages)
        started = time.monotonic()
        tool_calls = 0
        denied_actions = 0
        model_failures = 0
        files_read: set[str] = set()
        changed_files: set[str] = set()
        generation = 0
        previous_fingerprint: str | None = None
        repeated = 0
        self._audit.append(
            TaskLifecycleEvent(task_id=task_id, event_type="task_started")
        )
        try:
            for turn in range(1, self._settings.max_turns + 1):
                if time.monotonic() - started > self._settings.max_duration_seconds:
                    raise ControllerLimitError("task exceeded wall-clock limit")
                try:
                    action = self._model.propose(task_id=task_id, messages=messages)
                except ModelProtocolError as error:
                    model_failures += 1
                    retrying = (
                        error.code == "invalid_action"
                        and model_failures <= self._settings.max_model_failures
                    )
                    self._audit.append(
                        ModelFailureEvent(
                            task_id=task_id,
                            error_code=error.code,
                            retrying=retrying,
                        )
                    )
                    if not retrying:
                        raise
                    self._append_message(
                        messages,
                        ChatMessage(
                            role="tool",
                            content=json.dumps(
                                {
                                    "ok": False,
                                    "error_code": "invalid_action",
                                    "instruction": (
                                        "Return one valid action. Always include only "
                                        "schema_version, task_id, rationale, type, "
                                        "plus: list_files(path,recursive), "
                                        "read_file(path), search_text(path,query,"
                                        "case_sensitive), apply_patch(patch), "
                                        "show_diff(no fields), or complete(summary). "
                                        "In particular, apply_patch must not contain "
                                        "path."
                                    ),
                                },
                                separators=(",", ":"),
                            ),
                        ),
                    )
                    continue
                fingerprint = self._fingerprint(action)
                if fingerprint == previous_fingerprint:
                    repeated += 1
                else:
                    previous_fingerprint = fingerprint
                    repeated = 1
                if repeated > self._settings.max_repeated_actions:
                    raise ControllerLimitError(
                        "model repeated the same action too often"
                    )

                decision = self._policy.evaluate(action)
                self._audit.append(
                    ActionDecisionEvent(
                        task_id=task_id,
                        action_id=action.action_id,
                        action_type=action.type,
                        decision=decision.kind,
                        reason_code=decision.reason_code,
                        executed=False,
                    )
                )
                if decision.kind is not DecisionKind.ALLOW:
                    denied_actions += 1
                    denial_payload: dict[str, object] = {
                        "action_id": str(action.action_id),
                        "ok": False,
                        "error_code": "policy_denied",
                        "reason_code": decision.reason_code,
                    }
                    if decision.reason_code == "invalid_patch":
                        denial_payload["instruction"] = (
                            "Return a raw unified diff in patch with exact line "
                            "counts. Use --- a/path and +++ b/path, followed by "
                            "a hunk such as @@ -1,1 +1,1 @@. Prefix every hunk "
                            "line with space, minus, or plus. Do not use a "
                            "Markdown fence or include path outside patch."
                        )
                    self._append_message(
                        messages,
                        ChatMessage(
                            role="tool",
                            content=json.dumps(denial_payload, separators=(",", ":")),
                        ),
                    )
                    continue

                if isinstance(action, CompleteAction):
                    report = InspectionReport(
                        task_id=task_id,
                        status="completed",
                        model_summary=action.summary,
                        turns=turn,
                        tool_calls=tool_calls,
                        denied_actions=denied_actions,
                        model_failures=model_failures,
                        files_read=tuple(sorted(files_read)),
                        changed_files=tuple(sorted(changed_files)),
                        generation=generation,
                    )
                    self._audit.append(
                        TaskLifecycleEvent(
                            task_id=task_id,
                            event_type="task_completed",
                        )
                    )
                    return report

                if tool_calls >= self._settings.max_tool_calls:
                    raise ControllerLimitError("task exceeded tool-call limit")
                result = self._tools.execute(action)
                tool_calls += 1
                if isinstance(result, ReadFileResult) and result.ok:
                    files_read.add(result.path)
                if isinstance(result, ApplyPatchResult) and result.ok:
                    changed_files.update(result.changed_files)
                    generation = result.generation
                self._audit.append(
                    ToolFinishedEvent(
                        task_id=task_id,
                        action_id=action.action_id,
                        action_type=action.type,
                        ok=result.ok,
                        truncated=result.truncated,
                        error_code=result.error_code,
                    )
                )
                if isinstance(result, ApplyPatchResult) and result.ok:
                    if result.parent_tree_sha256 is None or result.tree_sha256 is None:
                        raise RuntimeError(
                            "successful patch result omitted manifest metadata"
                        )
                    self._audit.append(
                        WorkspaceGenerationEvent(
                            task_id=task_id,
                            action_id=action.action_id,
                            generation=result.generation,
                            parent_tree_sha256=result.parent_tree_sha256,
                            tree_sha256=result.tree_sha256,
                        )
                    )
                if isinstance(result, RunTaskResult):
                    self._audit.append(
                        SandboxFinishedEvent(
                            task_id=task_id,
                            action_id=action.action_id,
                            recipe_name=result.recipe_name,
                            recipe_digest=result.recipe_digest,
                            image_digest=result.image_digest,
                            sandbox_profile_digest=result.sandbox_profile_digest,
                            ok=result.ok,
                            error_code=result.error_code,
                            exit_code=result.exit_code,
                            timed_out=result.timed_out,
                            cancelled=result.cancelled,
                            duration_ms=result.duration_ms,
                            output_bytes=result.output_bytes,
                            output_truncated=result.truncated,
                        )
                    )
                self._append_message(
                    messages,
                    ChatMessage(role="assistant", content=action.model_dump_json()),
                )
                self._append_message(
                    messages,
                    ChatMessage(role="tool", content=result.model_dump_json()),
                )
            raise ControllerLimitError("task exceeded turn limit")
        except BaseException:
            self._audit.append(
                TaskLifecycleEvent(
                    task_id=task_id,
                    event_type="task_failed",
                    reason_code="controller_error",
                )
            )
            raise

    def _append_message(
        self, messages: list[ChatMessage], message: ChatMessage
    ) -> None:
        messages.append(message)
        self._check_context(messages)

    def _check_context(self, messages: list[ChatMessage]) -> None:
        context_bytes = sum(
            len(message.content.encode("utf-8")) for message in messages
        )
        if context_bytes > self._settings.max_context_bytes:
            raise ControllerLimitError("task exceeded context byte limit")

    @staticmethod
    def _fingerprint(action: object) -> str:
        if not isinstance(action, BaseModel):
            raise TypeError("model adapter returned an invalid action object")
        payload = action.model_dump(
            mode="json",
            exclude={"action_id", "rationale"},
        )
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))
