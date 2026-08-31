# SPDX-License-Identifier: MPL-2.0

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ulg.actions import ApplyPatchAction, RunTaskAction
from ulg.approval import (
    ActionGrantScope,
    ApprovalGrant,
    GrantRejectedError,
    ScopedGrantStore,
    action_digest,
    config_digest,
    parse_grant_scope,
    recipe_digest,
)
from ulg.config import load_config
from ulg.config.models import AppConfig
from ulg.policy import BaselinePolicy, Decision, DecisionKind


def _config() -> AppConfig:
    return load_config(Path("config/policy.example.toml"))


def _deletion(task_id: UUID | None = None) -> ApplyPatchAction:
    return ApplyPatchAction(
        task_id=task_id or uuid4(),
        rationale="remove obsolete file",
        patch="--- a/old.txt\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-old\n",
    )


def _run(task_id: UUID | None = None, recipe: str = "test") -> RunTaskAction:
    return RunTaskAction(
        task_id=task_id or uuid4(),
        rationale="verify the task",
        recipe_name=recipe,
    )


def test_grant_models_are_strict_and_require_safe_invariants() -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    scope = ActionGrantScope(
        action_id=uuid4(),
        action_digest="sha256:" + "a" * 64,
    )

    with pytest.raises(ValidationError):
        ApprovalGrant(
            task_id=uuid4(),
            scope=scope,
            config_digest="invalid",
            issued_at=now,
            expires_at=now + timedelta(minutes=1),
            max_uses=1,
        )
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        ApprovalGrant(
            task_id=uuid4(),
            scope=scope,
            config_digest="sha256:" + "b" * 64,
            issued_at=now.replace(tzinfo=None),
            expires_at=now + timedelta(minutes=1),
            max_uses=1,
        )
    with pytest.raises(ValidationError, match="single-use"):
        ApprovalGrant(
            task_id=uuid4(),
            scope=scope,
            config_digest="sha256:" + "b" * 64,
            issued_at=now,
            expires_at=now + timedelta(minutes=1),
            max_uses=2,
        )
    with pytest.raises(ValidationError):
        parse_grant_scope(
            {
                **scope.model_dump(),
                "unexpected": True,
            }
        )


def test_exact_action_grant_is_single_use_and_payload_bound() -> None:
    config = _config()
    action = _deletion()
    decision = BaselinePolicy(
        config.tools.apply_patch,
        config.tools.run_task,
    ).evaluate(action)
    store = ScopedGrantStore()
    grant = store.issue_action(
        decision=decision,
        action=action,
        config=config,
        ttl_seconds=60,
    )

    altered = action.model_copy(update={"rationale": "changed after approval"})
    with pytest.raises(GrantRejectedError, match="grant_action_mismatch"):
        store.consume_action(grant.grant_id, action=altered, config=config)
    assert store.remaining_uses(grant.grant_id) == 1

    assert store.consume_action(grant.grant_id, action=action, config=config) == grant
    assert store.remaining_uses(grant.grant_id) == 0
    with pytest.raises(GrantRejectedError, match="grant_exhausted"):
        store.consume_action(grant.grant_id, action=action, config=config)


def test_grant_issuance_requires_the_matching_ask_decision() -> None:
    config = _config()
    action = _deletion()
    store = ScopedGrantStore()

    with pytest.raises(ValueError, match="only ASK"):
        store.issue_action(
            decision=Decision(
                action_id=action.action_id,
                kind=DecisionKind.DENY,
                reason_code="test_denial",
            ),
            action=action,
            config=config,
            ttl_seconds=60,
        )
    with pytest.raises(ValueError, match="does not match"):
        store.issue_action(
            decision=Decision(
                action_id=uuid4(),
                kind=DecisionKind.ASK,
                reason_code="test_approval",
            ),
            action=action,
            config=config,
            ttl_seconds=60,
        )
    with pytest.raises(ValueError, match="between 1 and 86400"):
        store.issue_action(
            decision=Decision(
                action_id=action.action_id,
                kind=DecisionKind.ASK,
                reason_code="test_approval",
            ),
            action=action,
            config=config,
            ttl_seconds=86_401,
        )


def test_task_and_configuration_changes_revoke_a_grant() -> None:
    config = _config()
    action = _deletion()
    decision = BaselinePolicy(config.tools.apply_patch).evaluate(action)
    store = ScopedGrantStore()
    grant = store.issue_action(
        decision=decision,
        action=action,
        config=config,
        ttl_seconds=60,
    )

    wrong_task = action.model_copy(update={"task_id": uuid4()})
    with pytest.raises(GrantRejectedError, match="grant_task_mismatch"):
        store.consume_action(grant.grant_id, action=wrong_task, config=config)

    changed_payload = config.model_dump()
    changed_payload["task"]["max_turns"] += 1
    changed_config = AppConfig.model_validate(changed_payload)
    with pytest.raises(GrantRejectedError, match="grant_config_changed"):
        store.consume_action(grant.grant_id, action=action, config=changed_config)


def test_expired_and_forged_grants_are_rejected() -> None:
    now = [datetime(2026, 8, 8, tzinfo=UTC)]
    config = _config()
    action = _deletion()
    decision = BaselinePolicy(config.tools.apply_patch).evaluate(action)
    store = ScopedGrantStore(clock=lambda: now[0])
    grant = store.issue_action(
        decision=decision,
        action=action,
        config=config,
        ttl_seconds=10,
    )

    now[0] += timedelta(seconds=10)
    with pytest.raises(GrantRejectedError, match="grant_expired"):
        store.consume_action(grant.grant_id, action=action, config=config)
    with pytest.raises(GrantRejectedError, match="grant_not_found"):
        store.consume_action(uuid4(), action=action, config=config)


def test_recipe_grant_binds_recipe_and_rejects_action_replay() -> None:
    config = _config()
    task_id = uuid4()
    action = _run(task_id)
    decision = BaselinePolicy(run_settings=config.tools.run_task).evaluate(action)
    store = ScopedGrantStore()
    grant = store.issue_recipe(decision=decision, action=action, config=config)

    wrong_recipe = _run(task_id, "lint")
    with pytest.raises(GrantRejectedError, match="grant_recipe_mismatch"):
        store.consume_recipe(grant.grant_id, action=wrong_recipe, config=config)

    store.consume_recipe(grant.grant_id, action=action, config=config)
    with pytest.raises(GrantRejectedError, match="grant_action_replayed"):
        store.consume_recipe(grant.grant_id, action=action, config=config)


def test_recipe_grant_use_limit_is_atomic() -> None:
    config = _config()
    task_id = uuid4()
    initial = _run(task_id)
    decision = BaselinePolicy(run_settings=config.tools.run_task).evaluate(initial)
    store = ScopedGrantStore()
    grant = store.issue_recipe(decision=decision, action=initial, config=config)
    actions = [_run(task_id) for _ in range(10)]

    def consume(action: RunTaskAction) -> bool:
        try:
            store.consume_recipe(grant.grant_id, action=action, config=config)
        except GrantRejectedError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=10) as executor:
        accepted = list(executor.map(consume, actions))

    assert sum(accepted) == config.tools.run_task.grant_max_uses
    assert store.remaining_uses(grant.grant_id) == 0


def test_digests_are_deterministic_and_security_relevant() -> None:
    config = _config()
    action = _run()

    assert action_digest(action) == action_digest(action)
    assert config_digest(config) == config_digest(config)
    assert recipe_digest("test", config) == recipe_digest("test", config)

    changed_payload = config.model_dump()
    changed_payload["sandbox"]["wall_time_seconds"] += 1
    changed = AppConfig.model_validate(changed_payload)
    assert config_digest(changed) != config_digest(config)
    assert recipe_digest("test", changed) != recipe_digest("test", config)
