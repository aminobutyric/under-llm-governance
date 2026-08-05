# SPDX-License-Identifier: MPL-2.0

from typing import Protocol

from ulg.actions import (
    Action,
    ApplyPatchAction,
    CompleteAction,
    ListFilesAction,
    ReadFileAction,
    RunTaskAction,
    SearchTextAction,
    ShowDiffAction,
)
from ulg.config.models import ApplyPatchTool, RunTaskTool
from ulg.policy.models import Decision, DecisionKind
from ulg.workspace.patches import PatchError, parse_unified_diff


class PolicyEngine(Protocol):
    def evaluate(self, action: Action) -> Decision: ...


class BaselinePolicy:
    """Deterministic MVP policy for reads, diffs, and disposable patches."""

    def __init__(
        self,
        patch_settings: ApplyPatchTool | None = None,
        run_settings: RunTaskTool | None = None,
    ) -> None:
        self._patch_settings = patch_settings
        self._run_settings = run_settings

    def evaluate(self, action: Action) -> Decision:
        if isinstance(action, ApplyPatchAction):
            kind, reason_code = self._evaluate_patch(action)
        elif isinstance(action, RunTaskAction):
            kind, reason_code = self._evaluate_run_task(action)
        elif isinstance(action, ShowDiffAction):
            kind = DecisionKind.ALLOW
            reason_code = "baseline_diff"
        elif isinstance(
            action,
            (ListFilesAction, ReadFileAction, SearchTextAction, CompleteAction),
        ):
            kind = DecisionKind.ALLOW
            reason_code = "baseline_read_only"
        else:
            kind = DecisionKind.DENY
            reason_code = "action_not_allowed"
        return Decision(
            action_id=action.action_id,
            kind=kind,
            reason_code=reason_code,
        )

    def _evaluate_patch(self, action: ApplyPatchAction) -> tuple[DecisionKind, str]:
        if self._patch_settings is None:
            return DecisionKind.DENY, "patch_policy_unavailable"
        try:
            patches = parse_unified_diff(action.patch)
        except PatchError:
            return DecisionKind.DENY, "invalid_patch"
        if len(action.patch.encode()) > self._patch_settings.max_patch_bytes:
            return DecisionKind.DENY, "patch_too_large"
        if len(patches) > self._patch_settings.max_changed_files:
            return DecisionKind.DENY, "too_many_changed_files"
        if len(patches) > self._patch_settings.ask_above_changed_files or (
            self._patch_settings.ask_on_delete
            and any(patch.operation == "delete" for patch in patches)
        ):
            return DecisionKind.ASK, "patch_requires_approval"
        return DecisionKind.ALLOW, "baseline_small_patch"

    def _evaluate_run_task(self, action: RunTaskAction) -> tuple[DecisionKind, str]:
        if self._run_settings is None:
            return DecisionKind.DENY, "run_policy_unavailable"
        if action.recipe_name not in self._run_settings.allowed_recipes:
            return DecisionKind.DENY, "recipe_not_allowed"
        return DecisionKind.ASK, "recipe_requires_approval"
