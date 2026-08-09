# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from ulg.actions import Action, RunTaskAction
from ulg.config.models import AppConfig
from ulg.policy import Decision, DecisionKind

Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
_MAX_GRANT_TTL_SECONDS = 86_400
RecipeName = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$"),
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ActionGrantScope(_StrictModel):
    """A one-use capability for one exact, immutable action payload."""

    type: Literal["action"] = "action"
    action_id: UUID
    action_digest: Sha256Digest


class RecipeGrantScope(_StrictModel):
    """A bounded capability for one trusted recipe and sandbox definition."""

    type: Literal["recipe"] = "recipe"
    recipe_name: RecipeName
    recipe_digest: Sha256Digest


GrantScope = Annotated[
    ActionGrantScope | RecipeGrantScope,
    Field(discriminator="type"),
]
_SCOPE_ADAPTER: TypeAdapter[GrantScope] = TypeAdapter(GrantScope)


class ApprovalGrant(_StrictModel):
    """Controller-issued capability that is never authored by the model."""

    schema_version: Literal[1] = 1
    grant_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    scope: GrantScope
    config_digest: Sha256Digest
    issued_at: datetime
    expires_at: datetime
    max_uses: int = Field(gt=0, le=1_000)

    @field_validator("issued_at", "expires_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("grant timestamps must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def enforce_grant_invariants(self) -> ApprovalGrant:
        if self.expires_at <= self.issued_at:
            raise ValueError("grant expiry must be after issuance")
        if isinstance(self.scope, ActionGrantScope) and self.max_uses != 1:
            raise ValueError("exact-action grants must be single-use")
        return self


class GrantRejectedError(RuntimeError):
    """A presented grant did not authorize the requested action."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass
class _GrantState:
    grant: ApprovalGrant
    uses: int = 0
    action_ids: set[UUID] = field(default_factory=set)


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def action_digest(action: Action) -> str:
    """Hash every validated action field using canonical JSON."""

    return _digest(action.model_dump(mode="json"))


def config_digest(config: AppConfig) -> str:
    """Hash the complete trusted policy so any change revokes grants."""

    return _digest(config.model_dump(mode="json"))


def recipe_digest(recipe_name: str, config: AppConfig) -> str:
    """Bind a recipe name to its exact argv and sandbox security profile."""

    if recipe_name not in config.tools.run_task.allowed_recipes:
        raise ValueError("recipe is not allowlisted")
    recipe = config.recipes.get(recipe_name)
    if recipe is None:
        raise ValueError("recipe is not configured")
    return _digest(
        {
            "recipe_name": recipe_name,
            "recipe": recipe.model_dump(mode="json"),
            "sandbox": config.sandbox.model_dump(mode="json"),
        }
    )


class ScopedGrantStore:
    """Issue and atomically consume in-memory scoped approval grants.

    Persistence and user-facing approval prompts belong to later Phase 4
    iterations. Only trusted controller code should call the issuance methods.
    """

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._states: dict[UUID, _GrantState] = {}
        self._lock = Lock()

    def issue_action(
        self,
        *,
        decision: Decision,
        action: Action,
        config: AppConfig,
        ttl_seconds: int,
    ) -> ApprovalGrant:
        """Issue a one-use grant for the exact action that produced ``ASK``."""

        self._require_ask(decision, action)
        if not 0 < ttl_seconds <= _MAX_GRANT_TTL_SECONDS:
            raise ValueError("grant TTL must be between 1 and 86400 seconds")
        issued_at = self._utc_now()
        grant = ApprovalGrant(
            task_id=action.task_id,
            scope=ActionGrantScope(
                action_id=action.action_id,
                action_digest=action_digest(action),
            ),
            config_digest=config_digest(config),
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=ttl_seconds),
            max_uses=1,
        )
        return self._register(grant)

    def issue_recipe(
        self,
        *,
        decision: Decision,
        action: RunTaskAction,
        config: AppConfig,
    ) -> ApprovalGrant:
        """Issue a configured multi-use grant for one exact trusted recipe."""

        self._require_ask(decision, action)
        issued_at = self._utc_now()
        settings = config.tools.run_task
        grant = ApprovalGrant(
            task_id=action.task_id,
            scope=RecipeGrantScope(
                recipe_name=action.recipe_name,
                recipe_digest=recipe_digest(action.recipe_name, config),
            ),
            config_digest=config_digest(config),
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=settings.grant_ttl_seconds),
            max_uses=settings.grant_max_uses,
        )
        return self._register(grant)

    def consume_action(
        self,
        grant_id: UUID,
        *,
        action: Action,
        config: AppConfig,
    ) -> ApprovalGrant:
        """Consume an exact-action grant or reject without changing its state."""

        with self._lock:
            state = self._validated_common(grant_id, action, config)
            scope = state.grant.scope
            if not isinstance(scope, ActionGrantScope):
                raise GrantRejectedError("grant_scope_mismatch")
            if scope.action_id != action.action_id:
                raise GrantRejectedError("grant_action_mismatch")
            if scope.action_digest != action_digest(action):
                raise GrantRejectedError("grant_action_mismatch")
            self._consume(state, action.action_id)
            return state.grant

    def consume_recipe(
        self,
        grant_id: UUID,
        *,
        action: RunTaskAction,
        config: AppConfig,
    ) -> ApprovalGrant:
        """Consume one use for a matching recipe action and task."""

        with self._lock:
            state = self._validated_common(grant_id, action, config)
            scope = state.grant.scope
            if not isinstance(scope, RecipeGrantScope):
                raise GrantRejectedError("grant_scope_mismatch")
            if scope.recipe_name != action.recipe_name:
                raise GrantRejectedError("grant_recipe_mismatch")
            if scope.recipe_digest != recipe_digest(action.recipe_name, config):
                raise GrantRejectedError("grant_recipe_mismatch")
            self._consume(state, action.action_id)
            return state.grant

    def remaining_uses(self, grant_id: UUID) -> int:
        """Return bounded state for trusted status and test consumers."""

        with self._lock:
            state = self._states.get(grant_id)
            if state is None:
                raise GrantRejectedError("grant_not_found")
            return state.grant.max_uses - state.uses

    def _register(self, grant: ApprovalGrant) -> ApprovalGrant:
        with self._lock:
            if grant.grant_id in self._states:
                raise RuntimeError("duplicate grant identifier")
            self._states[grant.grant_id] = _GrantState(grant=grant)
        return grant

    def _validated_common(
        self,
        grant_id: UUID,
        action: Action,
        config: AppConfig,
    ) -> _GrantState:
        state = self._states.get(grant_id)
        if state is None:
            raise GrantRejectedError("grant_not_found")
        grant = state.grant
        if grant.config_digest != config_digest(config):
            raise GrantRejectedError("grant_config_changed")
        if grant.task_id != action.task_id:
            raise GrantRejectedError("grant_task_mismatch")
        if self._utc_now() >= grant.expires_at:
            raise GrantRejectedError("grant_expired")
        if state.uses >= grant.max_uses:
            raise GrantRejectedError("grant_exhausted")
        if action.action_id in state.action_ids:
            raise GrantRejectedError("grant_action_replayed")
        return state

    @staticmethod
    def _consume(state: _GrantState, action_id: UUID) -> None:
        state.uses += 1
        state.action_ids.add(action_id)

    @staticmethod
    def _require_ask(decision: Decision, action: Action) -> None:
        if decision.kind is not DecisionKind.ASK:
            raise ValueError("only ASK decisions can produce approval grants")
        if decision.action_id != action.action_id:
            raise ValueError("approval decision does not match action")

    def _utc_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise RuntimeError("grant clock must return timezone-aware UTC")
        return now


def parse_grant_scope(payload: object) -> GrantScope:
    """Strictly validate a serialized scope at a trusted persistence boundary."""

    return _SCOPE_ADAPTER.validate_python(payload)
