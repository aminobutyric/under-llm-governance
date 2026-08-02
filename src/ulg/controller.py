# SPDX-License-Identifier: MPL-2.0

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ulg.audit import AuditEvent, AuditSink
from ulg.model import ModelAdapter
from ulg.policy import Decision, DecisionKind
from ulg.policy.engine import PolicyEngine


class DryRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: UUID
    action_type: str
    decision: DecisionKind
    executed: bool


class Controller:
    """Trusted orchestration boundary. Phase 0 intentionally executes no tools."""

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
        action = self._model.propose(task_id=task_id, prompt=prompt)
        decision: Decision = self._policy.evaluate(action)
        self._audit.append(
            AuditEvent(
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
