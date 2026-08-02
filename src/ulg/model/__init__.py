# SPDX-License-Identifier: MPL-2.0
"""Provider-neutral model contracts and adapters."""

from ulg.model.base import ModelAdapter
from ulg.model.fake import FakeModel

__all__ = ["FakeModel", "ModelAdapter"]
