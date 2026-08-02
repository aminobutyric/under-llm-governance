# SPDX-License-Identifier: MPL-2.0
"""Provider-neutral model contracts and adapters."""

from ulg.model.base import ChatMessage, ModelAdapter
from ulg.model.fake import FakeModel
from ulg.model.ollama import ModelProtocolError, OllamaModel

__all__ = [
    "ChatMessage",
    "FakeModel",
    "ModelAdapter",
    "ModelProtocolError",
    "OllamaModel",
]
