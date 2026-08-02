# SPDX-License-Identifier: MPL-2.0

from typing import Protocol

from ulg.actions import Action
from ulg.tools.results import ToolResult

__all__ = ["ToolResult", "ToolRunner"]


class ToolRunner(Protocol):
    def execute(self, action: Action) -> ToolResult: ...
