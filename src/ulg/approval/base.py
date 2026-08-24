# SPDX-License-Identifier: MPL-2.0

from enum import StrEnum
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PatchApprovalRequest(_StrictModel):
    """Controller-normalized summary of an approval-sensitive patch."""

    type: Literal["patch"] = "patch"
    task_id: UUID
    action_id: UUID
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    changed_files: tuple[str, ...]
    deleted_files: tuple[str, ...]
    patch_bytes: int = Field(gt=0)
    ttl_seconds: int = Field(gt=0, le=86_400)


class RecipeApprovalRequest(_StrictModel):
    """Controller-normalized summary of one trusted sandbox recipe."""

    type: Literal["recipe"] = "recipe"
    task_id: UUID
    action_id: UUID
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    recipe_name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    argv: tuple[str, ...]
    recipe_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    network: Literal["none"]
    wall_time_seconds: int = Field(gt=0, le=600)
    memory_bytes: int = Field(gt=0)
    cpus: float = Field(gt=0)
    pids: int = Field(gt=0)
    grant_max_uses: int = Field(gt=0, le=1_000)
    grant_ttl_seconds: int = Field(gt=0, le=86_400)


ApprovalRequest = Annotated[
    PatchApprovalRequest | RecipeApprovalRequest,
    Field(discriminator="type"),
]


class ApprovalResolution(StrEnum):
    DENY = "deny"
    APPROVE_ONCE = "approve_once"
    APPROVE_RECIPE = "approve_recipe"


class ApprovalService(Protocol):
    """Render and resolve an ASK decision using normalized controller data."""

    def request(self, request: ApprovalRequest) -> ApprovalResolution: ...
