# SPDX-License-Identifier: MPL-2.0

from pathlib import Path
from uuid import uuid4

import pytest

from ulg.actions import ApplyPatchAction, RunTaskAction
from ulg.approval import GrantRejectedError, ScopedGrantStore, config_digest
from ulg.config import load_config
from ulg.policy import BaselinePolicy
from ulg.tasks import (
    DurableEffectJournal,
    TaskBusyError,
    TaskPhase,
    TaskState,
    TaskStateError,
    TaskStore,
)
from ulg.tools import CodingTools
from ulg.workspace import SnapshotWorkspaceManager

UPDATE_PATCH = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-old
+new
"""


def _task_state(tmp_path: Path, task_id: object) -> TaskState:
    from uuid import UUID

    assert isinstance(task_id, UUID)
    config_path = Path("config/policy.example.toml").resolve()
    config = load_config(config_path)
    source = (tmp_path / "source").resolve()
    source.mkdir(exist_ok=True)
    return TaskState(
        task_id=task_id,
        source_root=source,
        config_path=config_path,
        config_digest=config_digest(config),
        model_name=config.model.name,
        task_text="update the app",
        output_path=(tmp_path / "change.patch").resolve(),
    )


def test_task_store_revisions_are_atomic_and_lease_is_exclusive(tmp_path: Path) -> None:
    task_id = uuid4()
    store = TaskStore(tmp_path / "tasks")
    store.create(_task_state(tmp_path, task_id))

    with store.lease(task_id) as session:
        session.transition(TaskPhase.EXECUTE)
        assert session.state.revision == 1
        with (
            pytest.raises(TaskBusyError, match="already active"),
            store.lease(task_id),
        ):
            pass

    loaded = store.load(task_id)
    assert loaded.phase is TaskPhase.EXECUTE
    assert loaded.revision == 1
    assert (tmp_path / "tasks" / f"{task_id.hex}.json").stat().st_mode & 0o777 == 0o600


def test_failed_atomic_replace_preserves_previous_task_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_id = uuid4()
    store = TaskStore(tmp_path / "tasks")
    store.create(_task_state(tmp_path, task_id))

    def fail_replace(source: object, destination: object) -> None:
        del source, destination
        raise OSError("injected replace failure")

    monkeypatch.setattr("ulg.tasks.state.os.replace", fail_replace)
    with (
        store.lease(task_id) as session,
        pytest.raises(TaskStateError, match="committed"),
    ):
        session.transition(TaskPhase.EXECUTE)

    loaded = store.load(task_id)
    assert loaded.revision == 0
    assert loaded.phase is TaskPhase.PLAN
    assert not [
        path for path in (tmp_path / "tasks").iterdir() if path.name.endswith(".tmp")
    ]


def test_task_store_rejects_corrupt_or_stale_state(tmp_path: Path) -> None:
    task_id = uuid4()
    store = TaskStore(tmp_path / "tasks")
    state = _task_state(tmp_path, task_id)
    store.create(state)
    stale = state.model_copy(update={"revision": 1, "phase": TaskPhase.EXECUTE})

    with pytest.raises(TaskStateError, match="revision"):
        store.save(stale, expected_revision=1)

    state_path = tmp_path / "tasks" / f"{task_id.hex}.json"
    state_path.write_text('{"schema_version":')
    with pytest.raises(TaskStateError, match="malformed"):
        store.load(task_id)


def test_published_patch_is_recovered_after_interrupted_checkpoint(
    tmp_path: Path,
) -> None:
    task_id = uuid4()
    state = _task_state(tmp_path, task_id)
    source = state.source_root
    (source / "app.py").write_text("old\n")
    config = load_config(state.config_path)
    manager = SnapshotWorkspaceManager(tmp_path / "workspaces", config.workspace)
    workspace = manager.create(source=source, task_id=task_id)
    tools = CodingTools(
        workspace,
        manager,
        config.tools,
        original_root=source,
    )
    store = TaskStore(tmp_path / "tasks")
    store.create(state)
    action = ApplyPatchAction(
        task_id=task_id,
        rationale="update",
        patch=UPDATE_PATCH,
    )

    with store.lease(task_id) as session:
        journal = DurableEffectJournal(session)
        journal.before_execute(action)
        result = tools.execute(action)
        assert result.ok is True
        # Simulate process death before journal.after_execute().

    with store.lease(task_id) as resumed:
        recovered = manager.recover_latest(task_id=task_id, generation=0)
        pending = DurableEffectJournal(resumed).reconcile(
            recovered_generation=recovered.generation
        )

        assert pending is not None
        assert resumed.state.pending_effect is None
        assert resumed.state.generation == 1
        assert resumed.state.phase is TaskPhase.REVIEW
        assert resumed.state.effects[-1].outcome == "succeeded"
        assert (recovered.root / "app.py").read_text() == "new\n"


def test_consumed_recipe_grant_survives_restart_and_replay_is_rejected(
    tmp_path: Path,
) -> None:
    task_id = uuid4()
    state = _task_state(tmp_path, task_id)
    config = load_config(state.config_path)
    task_store = TaskStore(tmp_path / "tasks")
    task_store.create(state)
    action = RunTaskAction(task_id=task_id, rationale="verify", recipe_name="test")
    decision = BaselinePolicy(run_settings=config.tools.run_task).evaluate(action)
    grants = ScopedGrantStore(
        persist=lambda records: task_store.save_grants(task_id, records)
    )
    grant = grants.issue_recipe(decision=decision, action=action, config=config)
    grants.consume_recipe(grant.grant_id, action=action, config=config)

    restored = ScopedGrantStore(records=task_store.load_grants(task_id))

    assert restored.remaining_uses(grant.grant_id) == grant.max_uses - 1
    assert restored.active_recipe_grants(task_id=task_id, config=config) == {
        "test": grant.grant_id
    }
    with pytest.raises(GrantRejectedError, match="replayed"):
        restored.consume_recipe(grant.grant_id, action=action, config=config)


def test_interrupted_recipe_is_unknown_and_its_grant_is_revoked(tmp_path: Path) -> None:
    task_id = uuid4()
    state = _task_state(tmp_path, task_id)
    config = load_config(state.config_path)
    task_store = TaskStore(tmp_path / "tasks")
    task_store.create(state)
    action = RunTaskAction(task_id=task_id, rationale="verify", recipe_name="test")
    decision = BaselinePolicy(run_settings=config.tools.run_task).evaluate(action)
    grants = ScopedGrantStore(
        persist=lambda records: task_store.save_grants(task_id, records)
    )
    grant = grants.issue_recipe(decision=decision, action=action, config=config)
    grants.consume_recipe(grant.grant_id, action=action, config=config)

    with task_store.lease(task_id) as session:
        DurableEffectJournal(session).before_execute(action)

    restored = ScopedGrantStore(
        records=task_store.load_grants(task_id),
        persist=lambda records: task_store.save_grants(task_id, records),
    )
    with task_store.lease(task_id) as resumed:
        pending = DurableEffectJournal(resumed).reconcile(recovered_generation=0)
        assert pending is not None
        assert pending.recipe_name == "test"
        assert resumed.state.effects[-1].outcome == "unknown"
        assert resumed.state.phase is TaskPhase.RETRY
        restored.revoke_recipe(task_id=task_id, recipe_name="test")

    assert task_store.load_grants(task_id) == ()


def test_failed_grant_persistence_does_not_consume_in_memory_use(
    tmp_path: Path,
) -> None:
    task_id = uuid4()
    state = _task_state(tmp_path, task_id)
    config = load_config(state.config_path)
    action = RunTaskAction(task_id=task_id, rationale="verify", recipe_name="test")
    decision = BaselinePolicy(run_settings=config.tools.run_task).evaluate(action)
    fail = [False]

    def persist(records: object) -> None:
        del records
        if fail[0]:
            raise OSError("injected persistence failure")

    grants = ScopedGrantStore(persist=persist)
    grant = grants.issue_recipe(decision=decision, action=action, config=config)
    fail[0] = True

    with pytest.raises(OSError, match="injected"):
        grants.consume_recipe(grant.grant_id, action=action, config=config)

    assert grants.remaining_uses(grant.grant_id) == grant.max_uses
