# SPDX-License-Identifier: MPL-2.0

import os
import stat
from pathlib import Path
from typing import Protocol

from ulg.audit.events import AuditEvent


class AuditSink(Protocol):
    def append(self, event: AuditEvent) -> None: ...


class MemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


class JsonlAuditSink:
    """Append allowlisted events to a controller-selected local file."""

    def __init__(self, path: Path, *, max_event_bytes: int = 65_536) -> None:
        self._path = path
        self._max_event_bytes = max_event_bytes

    def append(self, event: AuditEvent) -> None:
        encoded = (event.model_dump_json() + "\n").encode()
        if len(encoded) > self._max_event_bytes:
            raise ValueError("audit event exceeds configured byte limit")
        try:
            file_fd = os.open(
                self._path,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
            )
        except OSError as error:
            raise ValueError("audit path cannot be opened safely") from error
        try:
            file_stat = os.fstat(file_fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError("audit sink is not a regular file")
            view = memoryview(encoded)
            while view:
                written = os.write(file_fd, view)
                if written <= 0:
                    raise ValueError("audit event append made no progress")
                view = view[written:]
            os.fsync(file_fd)
        finally:
            os.close(file_fd)
