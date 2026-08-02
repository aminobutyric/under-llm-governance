# SPDX-License-Identifier: MPL-2.0
"""Disposable task-workspace contracts."""

from ulg.workspace.base import WorkspaceManager, WorkspaceRef
from ulg.workspace.editor import PatchSummary, WorkspaceEditor
from ulg.workspace.exclusions import ExclusionPolicy
from ulg.workspace.manager import SnapshotError, SnapshotWorkspaceManager
from ulg.workspace.manifests import (
    GenerationManifest,
    ManifestEntry,
    ManifestError,
    build_manifest,
    scan_generation,
)
from ulg.workspace.patches import FilePatch, PatchError, parse_unified_diff
from ulg.workspace.paths import PathSecurityError, SecureRoot

__all__ = [
    "ExclusionPolicy",
    "FilePatch",
    "GenerationManifest",
    "ManifestEntry",
    "ManifestError",
    "PatchError",
    "PatchSummary",
    "PathSecurityError",
    "SecureRoot",
    "SnapshotError",
    "SnapshotWorkspaceManager",
    "WorkspaceEditor",
    "WorkspaceManager",
    "WorkspaceRef",
    "build_manifest",
    "parse_unified_diff",
    "scan_generation",
]
