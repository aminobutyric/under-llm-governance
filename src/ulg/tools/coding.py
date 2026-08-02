# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from pathlib import Path

from ulg.actions import (
    Action,
    ApplyPatchAction,
    ListFilesAction,
    ReadFileAction,
    SearchTextAction,
    ShowDiffAction,
)
from ulg.config.models import ToolsSettings
from ulg.tools.read_only import ReadOnlyTools
from ulg.tools.results import ApplyPatchResult, ShowDiffResult, ToolResult
from ulg.workspace import (
    GenerationManifest,
    PatchError,
    SecureRoot,
    SnapshotWorkspaceManager,
    WorkspaceEditor,
    WorkspaceRef,
)


class CodingTools:
    """Stateful task tools whose writes only publish disposable generations."""

    def __init__(
        self,
        workspace: WorkspaceRef,
        manager: SnapshotWorkspaceManager,
        settings: ToolsSettings,
        *,
        original_root: Path,
    ) -> None:
        self._workspace = workspace
        self._manager = manager
        self._settings = settings
        self._editor = WorkspaceEditor(
            manager,
            manager.exclusion_policy,
            settings.apply_patch,
            max_file_bytes=settings.read_file.max_bytes,
            original_root=original_root,
        )

    @property
    def workspace(self) -> WorkspaceRef:
        return self._workspace

    def execute(self, action: Action) -> ToolResult:
        if isinstance(action, (ListFilesAction, ReadFileAction, SearchTextAction)):
            with SecureRoot(self._workspace.root) as secure_root:
                tools = ReadOnlyTools(
                    secure_root,
                    self._manager.exclusion_policy,
                    list_settings=self._settings.list_files,
                    read_settings=self._settings.read_file,
                    search_settings=self._settings.search_text,
                )
                return tools.execute(action)
        if isinstance(action, ApplyPatchAction):
            return self._apply_patch(action)
        if isinstance(action, ShowDiffAction):
            return self._show_diff(action)
        raise TypeError(f"action {action.type!r} is not a coding tool action")

    def build_diff(self) -> str:
        return self._editor.build_diff(self._workspace)

    def export_diff(self, destination: Path) -> int:
        return self._editor.export_diff(self._workspace, destination)

    def source_manifest(self) -> GenerationManifest:
        source = WorkspaceRef(
            task_id=self._workspace.task_id,
            root=self._workspace.root.parent / "generation-0",
            generation=0,
        )
        return self._manager.read_manifest(source, verify=True)

    def current_manifest(self) -> GenerationManifest:
        return self._manager.read_manifest(self._workspace, verify=True)

    def _apply_patch(self, action: ApplyPatchAction) -> ApplyPatchResult:
        try:
            summary = self._editor.apply(self._workspace, action.patch)
        except PatchError as error:
            return ApplyPatchResult(
                action_id=action.action_id,
                ok=False,
                error_code="patch_rejected",
                generation=self._workspace.generation,
                correction=(
                    f"Patch was not applied: {str(error)[:430]}. Re-read the target "
                    "file and return a corrected unified diff."
                )[:500],
            )
        self._workspace = summary.workspace
        return ApplyPatchResult(
            action_id=action.action_id,
            ok=True,
            generation=self._workspace.generation,
            changed_files=summary.changed_files,
            deleted_files=summary.deleted_files,
            parent_tree_sha256=summary.parent_tree_sha256,
            tree_sha256=summary.tree_sha256,
        )

    def _show_diff(self, action: ShowDiffAction) -> ShowDiffResult:
        try:
            diff = self._editor.build_diff(self._workspace)
        except PatchError:
            return ShowDiffResult(
                action_id=action.action_id,
                ok=False,
                error_code="diff_failed",
                bytes_returned=0,
            )
        encoded = diff.encode("utf-8")
        limit = self._settings.show_diff.max_output_bytes
        truncated = len(encoded) > limit
        if truncated:
            encoded = encoded[:limit]
            while encoded:
                try:
                    diff = encoded.decode("utf-8")
                    break
                except UnicodeDecodeError:
                    encoded = encoded[:-1]
        return ShowDiffResult(
            action_id=action.action_id,
            ok=True,
            truncated=truncated,
            diff=diff,
            bytes_returned=len(encoded),
        )
