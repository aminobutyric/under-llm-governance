# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from collections.abc import Callable
from typing import TextIO

from ulg.actions import ApplyPatchAction, RunTaskAction
from ulg.approval.base import (
    ApprovalRequest,
    ApprovalResolution,
    PatchApprovalRequest,
    RecipeApprovalRequest,
)
from ulg.approval.grants import recipe_digest
from ulg.config.models import AppConfig
from ulg.policy import Decision
from ulg.workspace.patches import parse_unified_diff


def build_approval_request(
    *, action: ApplyPatchAction | RunTaskAction, decision: Decision, config: AppConfig
) -> ApprovalRequest:
    """Build display-safe approval data without carrying model-authored prose."""

    if decision.action_id != action.action_id:
        raise ValueError("approval decision does not match action")
    if isinstance(action, ApplyPatchAction):
        patches = parse_unified_diff(action.patch)
        return PatchApprovalRequest(
            task_id=action.task_id,
            action_id=action.action_id,
            reason_code=decision.reason_code,
            changed_files=tuple(patch.path for patch in patches),
            deleted_files=tuple(
                patch.path for patch in patches if patch.operation == "delete"
            ),
            patch_bytes=len(action.patch.encode("utf-8")),
            ttl_seconds=config.tools.apply_patch.grant_ttl_seconds,
        )
    recipe = config.recipes[action.recipe_name]
    sandbox = config.sandbox
    settings = config.tools.run_task
    return RecipeApprovalRequest(
        task_id=action.task_id,
        action_id=action.action_id,
        reason_code=decision.reason_code,
        recipe_name=action.recipe_name,
        argv=recipe.argv,
        recipe_digest=recipe_digest(action.recipe_name, config),
        image_digest=sandbox.image_digest,
        network=sandbox.network,
        wall_time_seconds=sandbox.wall_time_seconds,
        memory_bytes=sandbox.memory_bytes,
        cpus=sandbox.cpus,
        pids=sandbox.pids,
        grant_max_uses=settings.grant_max_uses,
        grant_ttl_seconds=settings.grant_ttl_seconds,
    )


class TerminalApprovalService:
    """Single-shot, fail-closed terminal approval interaction."""

    def __init__(
        self,
        *,
        input_fn: Callable[[], str],
        output: TextIO,
    ) -> None:
        self._input = input_fn
        self._output = output

    def request(self, request: ApprovalRequest) -> ApprovalResolution:
        self._render(request)
        try:
            answer = self._input().strip().casefold()
        except (EOFError, OSError):
            return ApprovalResolution.DENY
        if answer in {"y", "yes", "once", "o"}:
            return ApprovalResolution.APPROVE_ONCE
        if isinstance(request, RecipeApprovalRequest) and answer in {
            "r",
            "recipe",
        }:
            return ApprovalResolution.APPROVE_RECIPE
        return ApprovalResolution.DENY

    def _render(self, request: ApprovalRequest) -> None:
        write = self._output.write
        write("\nApproval required\n")
        write(f"  Task: {request.task_id}\n")
        write(f"  Action: {request.action_id}\n")
        if isinstance(request, PatchApprovalRequest):
            write(f"  Operation: modify {len(request.changed_files)} file(s)\n")
            for path in request.changed_files:
                marker = "delete" if path in request.deleted_files else "change"
                write(f"    - {marker}: {path}\n")
            write(f"  Patch size: {request.patch_bytes} bytes\n")
            write("Approve this exact action once? [y/N]: ")
        else:
            import json

            argv = " ".join(
                json.dumps(value, ensure_ascii=True) for value in request.argv
            )
            write(f"  Recipe: {request.recipe_name}\n")
            write(f"  Trusted command: {argv}\n")
            write(f"  Image: {request.image_digest}\n")
            write(
                "  Sandbox: network=none, "
                f"timeout={request.wall_time_seconds}s, "
                f"memory={request.memory_bytes // 1_048_576} MiB, "
                f"cpus={request.cpus:g}, "
                f"pids={request.pids}\n"
            )
            write(
                "  [o] approve once; "
                f"[r] approve this recipe up to {request.grant_max_uses} times "
                f"for {request.grant_ttl_seconds}s; [N] deny: "
            )
        self._output.flush()
