# SPDX-License-Identifier: MPL-2.0

from typing import Protocol

from ulg.policy import Decision


class ApprovalService(Protocol):
    """Render and resolve an ASK decision using normalized controller data."""

    def request(self, decision: Decision) -> bool: ...
