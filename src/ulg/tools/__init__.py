# SPDX-License-Identifier: MPL-2.0
"""Narrow tool execution contracts."""

from ulg.tools.base import ToolResult, ToolRunner
from ulg.tools.coding import CodingTools
from ulg.tools.read_only import ReadOnlyTools
from ulg.tools.results import (
    ApplyPatchResult,
    FileEntry,
    ListFilesResult,
    ReadFileResult,
    RunTaskResult,
    SearchMatch,
    SearchTextResult,
    ShowDiffResult,
)

__all__ = [
    "ApplyPatchResult",
    "CodingTools",
    "FileEntry",
    "ListFilesResult",
    "ReadFileResult",
    "ReadOnlyTools",
    "RunTaskResult",
    "SearchMatch",
    "SearchTextResult",
    "ShowDiffResult",
    "ToolResult",
    "ToolRunner",
]
