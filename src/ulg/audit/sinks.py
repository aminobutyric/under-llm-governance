# SPDX-License-Identifier: MPL-2.0

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
        with self._path.open("ab") as stream:
            stream.write(encoded)
