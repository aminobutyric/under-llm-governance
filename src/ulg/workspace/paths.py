# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from types import TracebackType


class PathSecurityError(ValueError):
    """A path failed the workspace containment contract."""


def relative_parts(path: str) -> tuple[str, ...]:
    if not path or "\x00" in path:
        raise PathSecurityError("path must be non-empty and NUL-free")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise PathSecurityError("path must remain relative to the workspace")
    return tuple(part for part in parsed.parts if part != ".")


def _identity(stat_result: os.stat_result) -> tuple[int, int, int]:
    return (stat_result.st_dev, stat_result.st_ino, stat_result.st_mode)


class SecureRoot:
    """Descriptor-relative, no-follow access beneath one already-open root."""

    def __init__(self, path: Path) -> None:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            self._fd = os.open(path, flags)
        except OSError as error:
            raise PathSecurityError("workspace root is not a safe directory") from error
        root_stat = os.fstat(self._fd)
        self._device = root_stat.st_dev
        self.path = path.absolute()

    @property
    def device(self) -> int:
        return self._device

    def __enter__(self) -> SecureRoot:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def duplicate_root(self) -> int:
        if self._fd < 0:
            raise RuntimeError("secure root is closed")
        return os.dup(self._fd)

    def open_child_directory(self, parent_fd: int, name: str) -> int:
        if name in {"", ".", ".."} or "/" in name or "\x00" in name:
            raise PathSecurityError("invalid directory component")
        try:
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
        except OSError as error:
            raise PathSecurityError("directory cannot be opened safely") from error
        after = os.fstat(child_fd)
        if _identity(before) != _identity(after) or after.st_dev != self._device:
            os.close(child_fd)
            raise PathSecurityError("directory identity or mount changed during open")
        return child_fd

    def open_directory(self, path: str) -> int:
        current_fd = self.duplicate_root()
        try:
            for part in relative_parts(path):
                next_fd = self.open_child_directory(current_fd, part)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except BaseException:
            os.close(current_fd)
            raise

    def open_regular_file(self, path: str) -> tuple[int, os.stat_result]:
        parts = relative_parts(path)
        if not parts:
            raise PathSecurityError("a regular-file path is required")
        parent_fd = self.duplicate_root()
        try:
            for part in parts[:-1]:
                next_fd = self.open_child_directory(parent_fd, part)
                os.close(parent_fd)
                parent_fd = next_fd
            name = parts[-1]
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            file_fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
            after = os.fstat(file_fd)
            if (
                _identity(before) != _identity(after)
                or after.st_dev != self._device
                or not stat.S_ISREG(after.st_mode)
            ):
                os.close(file_fd)
                raise PathSecurityError("path is not a contained regular file")
            return file_fd, after
        except OSError as error:
            raise PathSecurityError("file cannot be opened safely") from error
        finally:
            os.close(parent_fd)
