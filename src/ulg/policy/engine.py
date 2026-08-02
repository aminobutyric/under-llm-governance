# SPDX-License-Identifier: MPL-2.0

from typing import Protocol

from ulg.actions import Action
from ulg.policy.models import Decision, DecisionKind


class PolicyEngine(Protocol):
    def evaluate(self, action: Action) -> Decision: ...


class BaselinePolicy:
    """Small Phase 0 policy; effectful tools are not connected yet."""

    def evaluate(self, action: Action) -> Decision:
        return Decision(
            action_id=action.action_id,
            kind=DecisionKind.ALLOW,
            reason_code="phase0_dry_run",
        )
