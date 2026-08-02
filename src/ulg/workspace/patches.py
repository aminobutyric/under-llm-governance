# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ulg.workspace.paths import PathSecurityError, relative_parts

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?\n?$")


class PatchError(ValueError):
    """A unified diff is unsupported, malformed, stale, or unsafe."""


@dataclass(frozen=True)
class HunkLine:
    operation: Literal[" ", "+", "-"]
    content: str


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[HunkLine, ...]


@dataclass(frozen=True)
class FilePatch:
    path: str
    operation: Literal["create", "update", "delete"]
    hunks: tuple[Hunk, ...]

    def apply(self, source: str | None) -> str | None:
        if self.operation == "create" and source is not None:
            raise PatchError(f"create target already exists: {self.path}")
        if self.operation != "create" and source is None:
            raise PatchError(f"patch target does not exist: {self.path}")
        source_lines = [] if source is None else source.splitlines(keepends=True)
        output: list[str] = []
        cursor = 0
        for hunk in self.hunks:
            start = hunk.old_start if hunk.old_count == 0 else hunk.old_start - 1
            if start < cursor or start > len(source_lines):
                raise PatchError(f"hunks are overlapping or out of range: {self.path}")
            output.extend(source_lines[cursor:start])
            expected_new_start = (
                hunk.new_start if hunk.new_count == 0 else hunk.new_start - 1
            )
            if len(output) != expected_new_start:
                raise PatchError(f"hunk new-file position does not match: {self.path}")
            cursor = start
            for line in hunk.lines:
                if line.operation == "+":
                    output.append(line.content)
                    continue
                if cursor >= len(source_lines) or source_lines[cursor] != line.content:
                    raise PatchError(f"hunk context does not match: {self.path}")
                if line.operation == " ":
                    output.append(line.content)
                cursor += 1
        output.extend(source_lines[cursor:])
        result = "".join(output)
        if self.operation == "delete":
            if result:
                raise PatchError(f"delete patch leaves content behind: {self.path}")
            return None
        return result


def parse_unified_diff(payload: str) -> tuple[FilePatch, ...]:
    if not payload:
        raise PatchError("patch must not be empty")
    lines = payload.splitlines(keepends=True)
    patches: list[FilePatch] = []
    index = 0
    seen: set[str] = set()
    while index < len(lines):
        old_header = lines[index]
        if not old_header.startswith("--- "):
            raise PatchError("expected an old-file header")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise PatchError("expected a new-file header")
        new_header = lines[index]
        index += 1
        old_path = _header_path(old_header, "--- ")
        new_path = _header_path(new_header, "+++ ")
        path, operation = _normalize_file_paths(old_path, new_path)
        if path in seen:
            raise PatchError(f"file appears more than once in patch: {path}")
        seen.add(path)
        hunks: list[Hunk] = []
        while index < len(lines) and not lines[index].startswith("--- "):
            match = _HUNK_HEADER.match(lines[index])
            if match is None:
                raise PatchError(f"expected a hunk header for: {path}")
            index += 1
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_count = int(match.group(4) or "1")
            hunk_lines: list[HunkLine] = []
            seen_old = 0
            seen_new = 0
            while seen_old < old_count or seen_new < new_count:
                if index >= len(lines):
                    raise PatchError(f"hunk ended before its declared counts: {path}")
                line = lines[index]
                if line.startswith("\\ No newline at end of file"):
                    if not hunk_lines:
                        raise PatchError("newline marker has no preceding hunk line")
                    previous = hunk_lines[-1]
                    hunk_lines[-1] = HunkLine(
                        operation=previous.operation,
                        content=previous.content.removesuffix("\n"),
                    )
                    index += 1
                    continue
                if not line or line[0] not in {" ", "+", "-"}:
                    raise PatchError(f"invalid hunk line for: {path}")
                hunk_lines.append(
                    HunkLine(
                        operation=line[0],  # type: ignore[arg-type]
                        content=line[1:],
                    )
                )
                if line[0] in {" ", "-"}:
                    seen_old += 1
                if line[0] in {" ", "+"}:
                    seen_new += 1
                if seen_old > old_count or seen_new > new_count:
                    raise PatchError(f"hunk contains more lines than declared: {path}")
                index += 1
            if index < len(lines) and lines[index].startswith(
                "\\ No newline at end of file"
            ):
                previous = hunk_lines[-1]
                hunk_lines[-1] = HunkLine(
                    operation=previous.operation,
                    content=previous.content.removesuffix("\n"),
                )
                index += 1
            _validate_hunk_counts(path, old_count, new_count, hunk_lines)
            hunks.append(
                Hunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=tuple(hunk_lines),
                )
            )
        if not hunks:
            raise PatchError(f"file patch contains no hunks: {path}")
        if operation == "create" and any(hunk.old_count != 0 for hunk in hunks):
            raise PatchError(f"create patch consumes existing lines: {path}")
        if operation == "delete" and any(hunk.new_count != 0 for hunk in hunks):
            raise PatchError(f"delete patch produces new lines: {path}")
        patches.append(FilePatch(path=path, operation=operation, hunks=tuple(hunks)))
    return tuple(patches)


def _header_path(line: str, prefix: str) -> str:
    value = line[len(prefix) :].removesuffix("\n")
    if not value or any(ord(character) < 32 for character in value):
        raise PatchError("file headers cannot contain timestamps, tabs, or NUL")
    return value


def _normalize_file_paths(
    old_path: str, new_path: str
) -> tuple[str, Literal["create", "update", "delete"]]:
    if old_path == "/dev/null":
        if not new_path.startswith("b/"):
            raise PatchError("created file path must start with b/")
        path = new_path[2:]
        operation: Literal["create", "update", "delete"] = "create"
    elif new_path == "/dev/null":
        if not old_path.startswith("a/"):
            raise PatchError("deleted file path must start with a/")
        path = old_path[2:]
        operation = "delete"
    else:
        if not old_path.startswith("a/") or not new_path.startswith("b/"):
            raise PatchError("updated paths must use a/ and b/ prefixes")
        old_relative = old_path[2:]
        path = new_path[2:]
        if old_relative != path:
            raise PatchError("renames are not supported")
        operation = "update"
    try:
        parts = relative_parts(path)
    except PathSecurityError as error:
        raise PatchError("patch path escapes the workspace") from error
    if not parts:
        raise PatchError("patch path must name a file")
    return "/".join(parts), operation


def _validate_hunk_counts(
    path: str,
    old_count: int,
    new_count: int,
    lines: list[HunkLine],
) -> None:
    actual_old = sum(line.operation in {" ", "-"} for line in lines)
    actual_new = sum(line.operation in {" ", "+"} for line in lines)
    if actual_old != old_count or actual_new != new_count:
        raise PatchError(f"hunk counts do not match content: {path}")
