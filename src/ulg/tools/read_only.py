# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import os
import stat
from pathlib import PurePosixPath

from ulg.actions import Action, ListFilesAction, ReadFileAction, SearchTextAction
from ulg.config.models import ListFilesTool, ReadFileTool, SearchTextTool
from ulg.tools.results import (
    FileEntry,
    ListFilesResult,
    ReadFileResult,
    SearchMatch,
    SearchTextResult,
    ToolResult,
)
from ulg.workspace import ExclusionPolicy, PathSecurityError, SecureRoot


class ReadOnlyTools:
    """Bounded read-only operations against a disposable task snapshot."""

    def __init__(
        self,
        root: SecureRoot,
        exclusions: ExclusionPolicy,
        *,
        list_settings: ListFilesTool,
        read_settings: ReadFileTool,
        search_settings: SearchTextTool,
    ) -> None:
        self._root = root
        self._exclusions = exclusions
        self._list = list_settings
        self._read = read_settings
        self._search = search_settings

    def execute(self, action: Action) -> ToolResult:
        if isinstance(action, ListFilesAction):
            return self.list_files(action)
        if isinstance(action, ReadFileAction):
            return self.read_file(action)
        if isinstance(action, SearchTextAction):
            return self.search_text(action)
        raise TypeError(f"action {action.type!r} is not a read-only tool action")

    def list_files(self, action: ListFilesAction) -> ListFilesResult:
        if self._is_excluded(action.path, is_directory=True):
            return ListFilesResult(
                action_id=action.action_id,
                ok=False,
                error_code="excluded_path",
            )
        try:
            directory_fd = self._root.open_directory(action.path)
            try:
                base = self._as_relative(action.path)
                entries: list[FileEntry] = []
                state = _WalkState()
                self._list_directory(
                    directory_fd,
                    base,
                    depth=0,
                    recursive=action.recursive,
                    entries=entries,
                    state=state,
                )
            finally:
                os.close(directory_fd)
        except PathSecurityError:
            return ListFilesResult(
                action_id=action.action_id,
                ok=False,
                error_code="unsafe_path",
            )
        return ListFilesResult(
            action_id=action.action_id,
            ok=True,
            truncated=state.truncated,
            entries=tuple(entries),
        )

    def read_file(self, action: ReadFileAction) -> ReadFileResult:
        if self._is_excluded(action.path, is_directory=False):
            return self._read_error(action, "excluded_path")
        try:
            file_fd, file_stat = self._root.open_regular_file(action.path)
            try:
                limit = self._read.max_bytes
                payload = self._read_up_to(file_fd, limit + 1)
                final_stat = os.fstat(file_fd)
            finally:
                os.close(file_fd)
            if self._file_version(file_stat) != self._file_version(final_stat):
                return self._read_error(action, "file_changed")
        except PathSecurityError:
            return self._read_error(action, "unsafe_path")
        truncated = len(payload) > self._read.max_bytes
        payload = payload[: self._read.max_bytes]
        if b"\x00" in payload:
            return self._read_error(action, "binary_file")
        try:
            content = self._decode_prefix(payload, truncated=truncated)
        except UnicodeDecodeError:
            return self._read_error(action, "invalid_utf8")
        return ReadFileResult(
            action_id=action.action_id,
            ok=True,
            truncated=truncated,
            path=action.path,
            content=content,
            bytes_read=len(payload),
        )

    def search_text(self, action: SearchTextAction) -> SearchTextResult:
        if self._is_excluded(action.path, is_directory=True):
            return SearchTextResult(
                action_id=action.action_id,
                ok=False,
                error_code="excluded_path",
            )
        try:
            directory_fd = self._root.open_directory(action.path)
            try:
                matches: list[SearchMatch] = []
                state = _WalkState()
                self._search_directory(
                    directory_fd,
                    self._as_relative(action.path),
                    action,
                    depth=0,
                    matches=matches,
                    state=state,
                )
            finally:
                os.close(directory_fd)
        except PathSecurityError:
            return SearchTextResult(
                action_id=action.action_id,
                ok=False,
                error_code="unsafe_path",
            )
        return SearchTextResult(
            action_id=action.action_id,
            ok=True,
            truncated=state.truncated,
            matches=tuple(matches),
        )

    def _list_directory(
        self,
        directory_fd: int,
        relative: PurePosixPath,
        *,
        depth: int,
        recursive: bool,
        entries: list[FileEntry],
        state: _WalkState,
    ) -> None:
        for name in sorted(os.listdir(directory_fd)):
            if state.truncated:
                return
            entry_path = relative / name
            entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            is_directory = stat.S_ISDIR(entry_stat.st_mode)
            if self._is_excluded(entry_path.as_posix(), is_directory=is_directory):
                continue
            if stat.S_ISLNK(entry_stat.st_mode) or not (
                is_directory or stat.S_ISREG(entry_stat.st_mode)
            ):
                raise PathSecurityError("workspace contains an unsafe entry")
            entry = FileEntry(
                path=entry_path.as_posix(),
                kind="directory" if is_directory else "file",
                size=0 if is_directory else entry_stat.st_size,
            )
            estimated_bytes = len(entry.path.encode("utf-8")) + 64
            if (
                len(entries) >= self._list.max_entries
                or state.output_bytes + estimated_bytes > self._list.max_output_bytes
            ):
                state.truncated = True
                return
            entries.append(entry)
            state.output_bytes += estimated_bytes
            if is_directory and recursive:
                if depth >= self._list.max_depth:
                    state.truncated = True
                    continue
                child_fd = self._root.open_child_directory(directory_fd, name)
                try:
                    self._list_directory(
                        child_fd,
                        entry_path,
                        depth=depth + 1,
                        recursive=True,
                        entries=entries,
                        state=state,
                    )
                finally:
                    os.close(child_fd)

    def _search_directory(
        self,
        directory_fd: int,
        relative: PurePosixPath,
        action: SearchTextAction,
        *,
        depth: int,
        matches: list[SearchMatch],
        state: _WalkState,
    ) -> None:
        for name in sorted(os.listdir(directory_fd)):
            if state.truncated:
                return
            entry_path = relative / name
            entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            is_directory = stat.S_ISDIR(entry_stat.st_mode)
            if self._is_excluded(entry_path.as_posix(), is_directory=is_directory):
                continue
            if stat.S_ISLNK(entry_stat.st_mode) or not (
                is_directory or stat.S_ISREG(entry_stat.st_mode)
            ):
                raise PathSecurityError("workspace contains an unsafe entry")
            state.entries += 1
            if state.entries > self._list.max_entries:
                state.truncated = True
                return
            if is_directory:
                if depth >= self._list.max_depth:
                    state.truncated = True
                    continue
                child_fd = self._root.open_child_directory(directory_fd, name)
                try:
                    self._search_directory(
                        child_fd,
                        entry_path,
                        action,
                        depth=depth + 1,
                        matches=matches,
                        state=state,
                    )
                finally:
                    os.close(child_fd)
                continue
            if entry_stat.st_size > self._read.max_bytes:
                continue
            self._search_file(entry_path, action, matches, state)

    def _search_file(
        self,
        path: PurePosixPath,
        action: SearchTextAction,
        matches: list[SearchMatch],
        state: _WalkState,
    ) -> None:
        file_fd, opened_stat = self._root.open_regular_file(path.as_posix())
        try:
            payload = self._read_up_to(file_fd, self._read.max_bytes + 1)
            final_stat = os.fstat(file_fd)
        finally:
            os.close(file_fd)
        if (
            len(payload) > self._read.max_bytes
            or b"\x00" in payload
            or self._file_version(opened_stat) != self._file_version(final_stat)
        ):
            return
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError:
            return
        needle = action.query if action.case_sensitive else action.query.casefold()
        for line_number, line in enumerate(content.splitlines(), start=1):
            candidate = line if action.case_sensitive else line.casefold()
            if needle not in candidate:
                continue
            safe_line = line[:1_000]
            estimated_bytes = (
                len(path.as_posix().encode()) + len(safe_line.encode()) + 64
            )
            if (
                len(matches) >= self._search.max_matches
                or state.output_bytes + estimated_bytes > self._search.max_output_bytes
            ):
                state.truncated = True
                return
            matches.append(
                SearchMatch(
                    path=path.as_posix(),
                    line_number=line_number,
                    line=safe_line,
                )
            )
            state.output_bytes += estimated_bytes

    def _is_excluded(self, path: str, *, is_directory: bool) -> bool:
        return self._exclusions.is_permanently_excluded(
            self._as_relative(path), is_directory=is_directory
        )

    @staticmethod
    def _as_relative(path: str) -> PurePosixPath:
        parsed = PurePosixPath(path)
        return PurePosixPath(".") if str(parsed) == "." else parsed

    @staticmethod
    def _read_up_to(file_fd: int, limit: int) -> bytes:
        chunks: list[bytes] = []
        remaining = limit
        while remaining > 0:
            chunk = os.read(file_fd, min(128 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _decode_prefix(payload: bytes, *, truncated: bool) -> str:
        if not truncated:
            return payload.decode("utf-8")
        for trim in range(0, min(4, len(payload)) + 1):
            try:
                end = len(payload) - trim
                return payload[:end].decode("utf-8")
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError("utf-8", payload, 0, 1, "invalid UTF-8 prefix")

    @staticmethod
    def _file_version(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
        )

    @staticmethod
    def _read_error(action: ReadFileAction, code: str) -> ReadFileResult:
        return ReadFileResult(
            action_id=action.action_id,
            ok=False,
            error_code=code,
            path=action.path,
            bytes_read=0,
        )


class _WalkState:
    def __init__(self) -> None:
        self.entries = 0
        self.output_bytes = 0
        self.truncated = False
