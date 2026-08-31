# SPDX-License-Identifier: MPL-2.0

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from contextlib import ExitStack, suppress
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from ulg import __version__
from ulg.actions import ListFilesAction
from ulg.approval import ScopedGrantStore, TerminalApprovalService, config_digest
from ulg.audit import (
    AuditReadError,
    JsonlAuditSink,
    MemoryAuditSink,
    PatchExportedEvent,
    SandboxFinishedEvent,
    TaskLifecycleEvent,
    WorkspaceDiscardedEvent,
    read_audit_summary,
)
from ulg.config import ConfigError, load_config
from ulg.config.models import ModelSettings
from ulg.controller import Controller, ControllerLimitError, ReadOnlyController
from ulg.model import FakeModel, ModelProtocolError, OllamaModel
from ulg.policy import BaselinePolicy
from ulg.sandbox import (
    DockerPreflightError,
    RootlessDockerPreflight,
    RootlessDockerRunner,
    SandboxExecutionError,
)
from ulg.tasks import (
    DurableEffectJournal,
    TaskPhase,
    TaskSession,
    TaskState,
    TaskStateError,
    TaskStore,
    inspect_cleanup_candidate,
    remove_task_artifacts,
)
from ulg.tools import CodingTools, ReadOnlyTools
from ulg.workspace import (
    PathSecurityError,
    SecureRoot,
    SnapshotError,
    SnapshotWorkspaceManager,
    WorkspaceRef,
)


class _HelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
    def _get_help_string(self, action: argparse.Action) -> str:
        if action.required or action.default is None:
            return action.help or ""
        return super()._get_help_string(action) or ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ulg",
        description=(
            "Inspect, edit, and verify a selected directory through "
            "least-privilege local workflows."
        ),
        formatter_class=_HelpFormatter,
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser(
        "dry-run",
        help="exercise model, schema, policy, and audit contracts",
        formatter_class=_HelpFormatter,
    )
    dry_run.add_argument(
        "--path",
        default=".",
        help="relative action path used only by the contract dry run",
    )

    subparsers.add_parser(
        "sandbox-preflight",
        help="verify that the local Docker daemon meets sandbox requirements",
        formatter_class=_HelpFormatter,
    )

    sandbox_run = subparsers.add_parser(
        "sandbox-run",
        help="run one trusted recipe in a disposable offline sandbox",
        formatter_class=_HelpFormatter,
    )
    sandbox_run.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="source directory to snapshot; relative to the current directory",
    )
    sandbox_run.add_argument(
        "--recipe",
        required=True,
        help="recipe name allowlisted in the trusted policy",
    )
    _add_config_argument(sandbox_run)
    _add_state_argument(sandbox_run)

    inspect = subparsers.add_parser(
        "inspect",
        help="inspect a disposable read-only snapshot with Ollama",
        formatter_class=_HelpFormatter,
    )
    inspect.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="source directory to snapshot; relative to the current directory",
    )
    inspect.add_argument(
        "--task",
        required=True,
        help="inspection request sent to the selected local model",
    )
    inspect.add_argument(
        "--model",
        default=None,
        help="override the trusted local model name from the policy file",
    )
    _add_config_argument(inspect)
    _add_state_argument(inspect)

    run = subparsers.add_parser(
        "run",
        help="produce a reviewed patch in a disposable workspace",
        formatter_class=_HelpFormatter,
    )
    run.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="source directory to snapshot; relative to the current directory",
    )
    run.add_argument(
        "--task",
        required=True,
        help="coding request sent to the selected local model",
    )
    run.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new patch path; must not exist and must be outside the workspace",
    )
    run.add_argument(
        "--model",
        default=None,
        help="override the trusted local model name from the policy file",
    )
    _add_config_argument(run)
    _add_state_argument(run)
    run.add_argument(
        "--failure-mode",
        choices=("retain", "recover"),
        default="retain",
        help="retain for resume (default) or export/discard completed changes",
    )

    resume = subparsers.add_parser(
        "resume",
        help="resume a retained durable coding task",
        formatter_class=_HelpFormatter,
    )
    resume.add_argument("task_id", type=UUID)
    resume.add_argument("--config", type=Path, default=None)
    resume.add_argument("--output", type=Path, default=None)
    resume.add_argument("--model", default=None)
    _add_state_argument(resume)

    discard = subparsers.add_parser(
        "discard",
        help="destroy a retained task workspace and revoke its grants",
        formatter_class=_HelpFormatter,
    )
    discard.add_argument("task_id", type=UUID)
    discard.add_argument("--config", type=Path, default=None)
    _add_state_argument(discard)

    diff = subparsers.add_parser(
        "diff",
        help="review the bounded pending diff for a retained task",
        formatter_class=_HelpFormatter,
    )
    diff.add_argument("task_id", type=UUID)
    diff.add_argument("--config", type=Path, default=None)
    _add_state_argument(diff)

    audit = subparsers.add_parser(
        "audit",
        help="show a concise redacted lifecycle for a task",
        formatter_class=_HelpFormatter,
    )
    audit.add_argument("task_id", type=UUID)
    _add_state_argument(audit)

    clean = subparsers.add_parser(
        "clean",
        help="delete explicitly selected durable task artifacts",
        formatter_class=_HelpFormatter,
    )
    clean.add_argument("task_ids", nargs="+", type=UUID)
    clean.add_argument(
        "--older-than-days",
        type=_nonnegative_int,
        default=0,
        help="skip selected tasks newer than this age; zero disables the filter",
    )
    clean.add_argument(
        "--include-retained",
        action="store_true",
        help="allow deletion of resumable task workspaces",
    )
    clean.add_argument(
        "--yes",
        action="store_true",
        help="confirm the reported exact targets without an interactive prompt",
    )
    _add_state_argument(clean)
    return parser


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    configured = os.environ.get("ULG_CONFIG")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(configured) if configured else Path("config/policy.example.toml"),
        help=(
            "trusted policy TOML; set ULG_CONFIG for an invocation-independent "
            "default (a relative path is resolved from the current directory)"
        ),
    )


def _add_state_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help=(
            "application state root outside the workspace; defaults to "
            "$XDG_STATE_HOME/ulg or ~/.local/state/ulg"
        ),
    )


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "dry-run":
        task_id = uuid4()
        action = ListFilesAction(
            task_id=task_id,
            path=args.path,
            rationale="exercise the Phase 0 controller contract",
        )
        controller = Controller(
            model=FakeModel([action]),
            policy=BaselinePolicy(),
            audit=MemoryAuditSink(),
        )
        result = controller.dry_run_once(
            task_id=task_id,
            prompt="Phase 0 dry run",
        )
        print(result.model_dump_json())
        return 0
    if args.command == "sandbox-preflight":
        try:
            report = RootlessDockerPreflight().check()
        except DockerPreflightError as error:
            print(f"error: {_describe_error(error)}", file=sys.stderr)
            return 2
        print(json.dumps(report.to_dict(), separators=(",", ":")))
        return 0
    if args.command == "sandbox-run":
        return _run_sandbox_recipe(args)
    if args.command == "inspect":
        return _run_inspect(args)
    if args.command == "run":
        return _run_coding(args)
    if args.command == "resume":
        return _resume_coding(args)
    if args.command == "discard":
        return _discard_coding(args)
    if args.command == "diff":
        return _review_coding_diff(args)
    if args.command == "audit":
        return _review_task_audit(args)
    if args.command == "clean":
        return _clean_tasks(args)
    raise AssertionError("argparse accepted an unknown command")


def _run_inspect(args: argparse.Namespace) -> int:
    task_id = uuid4()
    state_root = args.state_dir or _default_state_root()
    workspace = None
    model = None
    try:
        _require_state_outside_workspace(args.workspace, state_root)
        config = load_config(args.config)
        manager = SnapshotWorkspaceManager(state_root / "workspaces", config.workspace)
        workspace = manager.create(source=args.workspace, task_id=task_id)
        audit_root = state_root / "audit"
        audit_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        audit = JsonlAuditSink(
            audit_root / f"{task_id}.jsonl",
            max_event_bytes=config.audit.max_event_bytes,
        )
        model_settings = config.model
        if args.model is not None:
            model_settings = ModelSettings.model_validate(
                {**config.model.model_dump(), "name": args.model}
            )
        model = OllamaModel(model_settings)
        with SecureRoot(workspace.root) as secure_root:
            tools = ReadOnlyTools(
                secure_root,
                manager.exclusion_policy,
                list_settings=config.tools.list_files,
                read_settings=config.tools.read_file,
                search_settings=config.tools.search_text,
            )
            controller = ReadOnlyController(
                model=model,
                policy=BaselinePolicy(),
                tools=tools,
                audit=audit,
                settings=config.task,
            )
            report = controller.run(task_id=task_id, task=args.task)
        print(report.model_dump_json())
        return 0
    except KeyboardInterrupt:
        print("task cancelled", file=sys.stderr)
        return 130
    except (
        ConfigError,
        ControllerLimitError,
        ModelProtocolError,
        PathSecurityError,
        SnapshotError,
        OSError,
        ValueError,
    ) as error:
        print(f"error: {_describe_error(error)}", file=sys.stderr)
        return 2
    finally:
        try:
            if model is not None:
                model.close()
        except Exception as error:
            print(f"warning: model client close failed: {error}", file=sys.stderr)
        finally:
            if workspace is not None:
                manager.discard(workspace)


def _run_sandbox_recipe(args: argparse.Namespace) -> int:
    task_id = uuid4()
    state_root = args.state_dir or _default_state_root()
    workspace = None
    audit: JsonlAuditSink | None = None
    cleanup_reason: Literal["completed", "failed", "cancelled"] = "failed"
    try:
        _require_state_outside_workspace(args.workspace, state_root)
        config = load_config(args.config)
        if args.recipe not in config.tools.run_task.allowed_recipes:
            raise ValueError("recipe is not allowlisted by trusted configuration")
        manager = SnapshotWorkspaceManager(state_root / "workspaces", config.workspace)
        workspace = manager.create(source=args.workspace, task_id=task_id)
        manager.seal_for_sandbox(workspace)
        audit_root = state_root / "audit"
        audit_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        audit = JsonlAuditSink(
            audit_root / f"{task_id}.jsonl",
            max_event_bytes=config.audit.max_event_bytes,
        )
        audit.append(TaskLifecycleEvent(task_id=task_id, event_type="task_started"))
        runner = RootlessDockerRunner(config.sandbox, config.recipes)
        result = runner.run(recipe_name=args.recipe, workspace=workspace.root)
        audit.append(
            SandboxFinishedEvent(
                task_id=task_id,
                recipe_name=result.recipe_name,
                recipe_digest=result.recipe_digest,
                image_digest=result.image_digest,
                sandbox_profile_digest=result.sandbox_profile_digest,
                ok=result.ok,
                error_code=result.error_code,
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                cancelled=result.cancelled,
                duration_ms=result.duration_ms,
                output_bytes=result.output_bytes,
                output_truncated=result.output_truncated,
            )
        )
        cleanup_reason = "cancelled" if result.cancelled else "completed"
        audit.append(
            TaskLifecycleEvent(
                task_id=task_id,
                event_type="task_failed" if result.cancelled else "task_completed",
                reason_code="sandbox_cancelled" if result.cancelled else None,
            )
        )
        print(result.model_dump_json())
        if result.cancelled:
            return 130
        return 0 if result.ok else 1
    except KeyboardInterrupt:
        cleanup_reason = "cancelled"
        print("sandbox task cancelled", file=sys.stderr)
        return 130
    except (
        ConfigError,
        DockerPreflightError,
        PathSecurityError,
        SandboxExecutionError,
        SnapshotError,
        OSError,
        ValueError,
    ) as error:
        print(f"error: {_describe_error(error)}", file=sys.stderr)
        return 2
    finally:
        if workspace is not None:
            if audit is not None:
                audit.append(
                    WorkspaceDiscardedEvent(
                        task_id=task_id,
                        generation=workspace.generation,
                        reason_code=cleanup_reason,
                        patch_exported=False,
                    )
                )
            manager.discard(workspace)


def _default_state_root() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    if configured:
        return Path(configured) / "ulg"
    return Path.home() / ".local" / "state" / "ulg"


def _require_state_outside_workspace(workspace: Path, state_root: Path) -> None:
    try:
        source = workspace.resolve(strict=True)
        state_targets = (
            (state_root / "workspaces").resolve(strict=False),
            (state_root / "audit").resolve(strict=False),
            (state_root / "tasks").resolve(strict=False),
        )
    except OSError as error:
        raise PathSecurityError(
            "cannot validate workspace and state separation"
        ) from error
    if any(
        target == source or target.is_relative_to(source) for target in state_targets
    ):
        raise PathSecurityError("application state cannot be inside the workspace")


def _run_coding(args: argparse.Namespace) -> int:
    task_id = uuid4()
    state_root = (args.state_dir or _default_state_root()).absolute()
    workspace = None
    manager: SnapshotWorkspaceManager | None = None
    persisted = False
    try:
        source_root = args.workspace.resolve(strict=True)
        config_path = args.config.resolve(strict=True)
        output_path = args.output.resolve(strict=False)
        _require_state_outside_workspace(source_root, state_root)
        config = load_config(config_path)
        manager = SnapshotWorkspaceManager(state_root / "workspaces", config.workspace)
        workspace = manager.create(source=source_root, task_id=task_id)
        model_name = args.model or config.model.name
        task_store = TaskStore(state_root / "tasks")
        task_store.create(
            TaskState(
                task_id=task_id,
                source_root=source_root,
                config_path=config_path,
                config_digest=config_digest(config),
                model_name=model_name,
                task_text=args.task,
                output_path=output_path,
                failure_mode=args.failure_mode,
            )
        )
        persisted = True
    except (
        ConfigError,
        PathSecurityError,
        SnapshotError,
        TaskStateError,
        OSError,
        ValueError,
    ) as error:
        if workspace is not None and manager is not None and not persisted:
            manager.discard(workspace)
        print(f"error: {_describe_error(error)}", file=sys.stderr)
        return 2
    _print_task_commands(task_id, state_root)
    return _execute_saved_task(task_id=task_id, state_root=state_root, resumed=False)


def _resume_coding(args: argparse.Namespace) -> int:
    state_root = (args.state_dir or _default_state_root()).absolute()
    return _execute_saved_task(
        task_id=args.task_id,
        state_root=state_root,
        resumed=True,
        config_override=args.config,
        output_override=args.output,
        model_override=args.model,
    )


def _execute_saved_task(
    *,
    task_id: UUID,
    state_root: Path,
    resumed: bool,
    config_override: Path | None = None,
    output_override: Path | None = None,
    model_override: str | None = None,
) -> int:
    store = TaskStore(state_root / "tasks")
    try:
        with store.lease(task_id) as session:
            return _execute_task_session(
                session=session,
                store=store,
                state_root=state_root,
                resumed=resumed,
                config_override=config_override,
                output_override=output_override,
                model_override=model_override,
            )
    except (
        ConfigError,
        PathSecurityError,
        SnapshotError,
        TaskStateError,
        OSError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _execute_task_session(
    *,
    session: TaskSession,
    store: TaskStore,
    state_root: Path,
    resumed: bool,
    config_override: Path | None,
    output_override: Path | None,
    model_override: str | None,
) -> int:
    state = session.state
    if state.phase in {TaskPhase.EXPORT, TaskPhase.DISCARD}:
        raise TaskStateError(f"task cannot be resumed from {state.phase} state")
    config_path = (
        config_override.resolve(strict=True)
        if config_override is not None
        else state.config_path
    )
    config = load_config(config_path)
    if config_digest(config) != state.config_digest:
        raise TaskStateError("trusted configuration changed since task creation")
    source_root = state.source_root.resolve(strict=True)
    _require_state_outside_workspace(source_root, state_root)
    output_path = (
        output_override.resolve(strict=False)
        if output_override is not None
        else state.output_path
    )
    model_name = model_override or state.model_name
    if (
        config_path != state.config_path
        or output_path != state.output_path
        or model_name != state.model_name
    ):
        session.update(
            config_path=config_path,
            output_path=output_path,
            model_name=model_name,
        )

    manager = SnapshotWorkspaceManager(state_root / "workspaces", config.workspace)
    workspace = manager.recover_latest(
        task_id=state.task_id,
        generation=session.state.generation,
    )
    grants = ScopedGrantStore(
        records=store.load_grants(state.task_id),
        persist=lambda records: store.save_grants(state.task_id, records),
    )
    journal = DurableEffectJournal(session)
    interrupted = journal.reconcile(recovered_generation=workspace.generation)
    if interrupted is not None and interrupted.recipe_name is not None:
        grants.revoke_recipe(
            task_id=state.task_id,
            recipe_name=interrupted.recipe_name,
        )
    session.transition(TaskPhase.EXECUTE, last_error_code=None)

    audit_root = state_root / "audit"
    audit_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    audit = JsonlAuditSink(
        audit_root / f"{state.task_id}.jsonl",
        max_event_bytes=config.audit.max_event_bytes,
    )
    model_settings = ModelSettings.model_validate(
        {**config.model.model_dump(), "name": model_name}
    )
    model = OllamaModel(
        model_settings,
        enable_run_task=True,
        allowed_recipes=config.tools.run_task.allowed_recipes,
    )
    tools = CodingTools(
        workspace,
        manager,
        config.tools,
        original_root=source_root,
        sandbox=RootlessDockerRunner(config.sandbox, config.recipes),
    )
    try:
        controller = ReadOnlyController(
            model=model,
            policy=BaselinePolicy(
                config.tools.apply_patch,
                config.tools.run_task,
            ),
            tools=tools,
            audit=audit,
            settings=config.task,
            config=config,
            approval=TerminalApprovalService(input_fn=input, output=sys.stderr),
            grants=grants,
            effect_journal=journal,
        )
        task_text = state.task_text
        if resumed:
            task_text = (
                "Resume this retained task from its verified disposable workspace. "
                "Re-inspect current files and do not assume an interrupted effect "
                f"succeeded. Original task:\n{state.task_text}"
            )
        report = controller.run(task_id=state.task_id, task=task_text, resumed=resumed)
        session.transition(TaskPhase.REVIEW, generation=tools.workspace.generation)
        diff = _export_coding_patch(
            tools=tools,
            destination=output_path,
            audit=audit,
            max_diff_bytes=config.tools.show_diff.max_output_bytes,
            recovered_after_failure=False,
        )
        session.transition(TaskPhase.EXPORT)
        _discard_task_workspace(
            session=session,
            store=store,
            manager=manager,
            workspace=tools.workspace,
            audit=audit,
            reason="completed",
            patch_exported=True,
        )
        audit_summary = read_audit_summary(
            audit_root / f"{state.task_id}.jsonl", task_id=state.task_id
        )
        print(
            json.dumps(
                {
                    "task_id": str(state.task_id),
                    "report": report.model_dump(mode="json"),
                    "diff": diff,
                    "exported_patch": str(output_path),
                    "state": TaskPhase.DISCARD.value,
                    "audit_summary": audit_summary.model_dump(mode="json"),
                    "next_commands": {
                        "audit": _command("audit", state.task_id, state_root),
                    },
                },
                separators=(",", ":"),
            )
        )
        return 0
    except KeyboardInterrupt:
        _safe_transition(session, TaskPhase.CANCEL, "task_cancelled")
        if session.state.failure_mode == "recover":
            _recover_and_discard_task(
                session=session,
                store=store,
                manager=manager,
                tools=tools,
                audit=audit,
                output_path=output_path,
                reason="cancelled",
                max_diff_bytes=config.tools.show_diff.max_output_bytes,
            )
        else:
            _print_resume_hint(state.task_id, state_root, "task cancelled and retained")
        return 130
    except (
        ConfigError,
        ControllerLimitError,
        ModelProtocolError,
        PathSecurityError,
        SnapshotError,
        TaskStateError,
        OSError,
        ValueError,
    ) as error:
        _safe_transition(session, TaskPhase.RETRY, _error_code(error))
        if session.state.failure_mode == "recover":
            _recover_and_discard_task(
                session=session,
                store=store,
                manager=manager,
                tools=tools,
                audit=audit,
                output_path=output_path,
                reason="failed",
                max_diff_bytes=config.tools.show_diff.max_output_bytes,
            )
        else:
            _print_resume_hint(
                state.task_id,
                state_root,
                f"task retained: {_describe_error(error)}",
            )
        return 2
    finally:
        try:
            model.close()
        except Exception as error:
            print(f"warning: model client close failed: {error}", file=sys.stderr)


def _safe_transition(session: TaskSession, phase: TaskPhase, error_code: str) -> None:
    with suppress(TaskStateError):
        session.transition(phase, last_error_code=error_code)


def _error_code(error: BaseException) -> str:
    if isinstance(error, ControllerLimitError):
        return "controller_limit"
    if isinstance(error, ModelProtocolError):
        return "model_protocol_error"
    if isinstance(error, SnapshotError):
        return "workspace_error"
    if isinstance(error, PathSecurityError):
        return "path_security_error"
    if isinstance(error, TaskStateError):
        return "task_state_error"
    return "task_error"


def _describe_error(error: BaseException) -> str:
    if isinstance(error, ModelProtocolError):
        if error.code in {"transport", "transport_error"}:
            return (
                "Ollama is unavailable at the configured local endpoint; start "
                "Ollama and verify the selected model is installed"
            )
        if error.code == "timeout":
            return (
                "Ollama timed out; verify the local service and model, then resume "
                "the retained task"
            )
        if error.code == "api_error":
            return (
                "Ollama rejected the request; verify the configured model name "
                "and local service status"
            )
    if isinstance(error, DockerPreflightError):
        return (
            f"{error}; start the rootless user Docker service and run "
            "`ulg sandbox-preflight` for details"
        )
    return str(error)


def _print_resume_hint(task_id: UUID, state_root: Path, message: str) -> None:
    print(
        f"{message}\ntask_id: {task_id}\n"
        f"diff: {_command('diff', task_id, state_root)}\n"
        f"audit: {_command('audit', task_id, state_root)}\n"
        f"resume: {_command('resume', task_id, state_root)}\n"
        f"discard: {_command('discard', task_id, state_root)}",
        file=sys.stderr,
    )


def _print_task_commands(task_id: UUID, state_root: Path) -> None:
    print(
        f"task_id: {task_id}\n"
        f"audit: {_command('audit', task_id, state_root)}\n"
        f"diff if retained: {_command('diff', task_id, state_root)}",
        file=sys.stderr,
    )


def _command(name: str, task_id: UUID, state_root: Path) -> str:
    return f"ulg {name} {task_id} --state-dir {state_root}"


def _recover_and_discard_task(
    *,
    session: TaskSession,
    store: TaskStore,
    manager: SnapshotWorkspaceManager,
    tools: CodingTools,
    audit: JsonlAuditSink,
    output_path: Path,
    reason: Literal["failed", "cancelled"],
    max_diff_bytes: int,
) -> None:
    patch_exported = _try_recovery_export(
        tools=tools,
        destination=output_path,
        audit=audit,
        max_diff_bytes=max_diff_bytes,
    )
    if patch_exported:
        _safe_transition(
            session, TaskPhase.EXPORT, session.state.last_error_code or reason
        )
    _discard_task_workspace(
        session=session,
        store=store,
        manager=manager,
        workspace=tools.workspace,
        audit=audit,
        reason=reason,
        patch_exported=patch_exported,
    )


def _discard_task_workspace(
    *,
    session: TaskSession,
    store: TaskStore,
    manager: SnapshotWorkspaceManager,
    workspace: WorkspaceRef,
    audit: JsonlAuditSink,
    reason: Literal["completed", "failed", "cancelled", "discarded"],
    patch_exported: bool,
) -> None:
    audit.append(
        WorkspaceDiscardedEvent(
            task_id=workspace.task_id,
            generation=workspace.generation,
            reason_code=reason,
            patch_exported=patch_exported,
        )
    )
    manager.discard(workspace)
    store.delete_grants(workspace.task_id)
    session.transition(TaskPhase.DISCARD, generation=workspace.generation)


def _discard_coding(args: argparse.Namespace) -> int:
    state_root = (args.state_dir or _default_state_root()).absolute()
    store = TaskStore(state_root / "tasks")
    try:
        with store.lease(args.task_id) as session:
            state = session.state
            if state.phase is TaskPhase.DISCARD:
                print(json.dumps({"task_id": str(state.task_id), "state": "discard"}))
                return 0
            config_path = (
                args.config.resolve(strict=True)
                if args.config is not None
                else state.config_path
            )
            config = load_config(config_path)
            manager = SnapshotWorkspaceManager(
                state_root / "workspaces", config.workspace
            )
            workspace = WorkspaceRef(
                task_id=state.task_id,
                root=(
                    state_root
                    / "workspaces"
                    / state.task_id.hex
                    / f"generation-{state.generation}"
                ),
                generation=state.generation,
            )
            audit_root = state_root / "audit"
            audit_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            audit = JsonlAuditSink(
                audit_root / f"{state.task_id}.jsonl",
                max_event_bytes=config.audit.max_event_bytes,
            )
            _discard_task_workspace(
                session=session,
                store=store,
                manager=manager,
                workspace=workspace,
                audit=audit,
                reason="discarded",
                patch_exported=False,
            )
            print(json.dumps({"task_id": str(state.task_id), "state": "discard"}))
            return 0
    except (ConfigError, SnapshotError, TaskStateError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _review_coding_diff(args: argparse.Namespace) -> int:
    state_root = (args.state_dir or _default_state_root()).absolute()
    store = TaskStore(state_root / "tasks")
    try:
        with store.lease(args.task_id) as session:
            state = session.state
            if state.phase is TaskPhase.DISCARD:
                raise TaskStateError("task workspace was already discarded")
            config_path = (
                args.config.resolve(strict=True)
                if args.config is not None
                else state.config_path
            )
            config = load_config(config_path)
            if config_digest(config) != state.config_digest:
                raise TaskStateError(
                    "trusted configuration changed since task creation"
                )
            manager = SnapshotWorkspaceManager(
                state_root / "workspaces", config.workspace
            )
            workspace = manager.recover_latest(
                task_id=state.task_id,
                generation=state.generation,
            )
            tools = CodingTools(
                workspace,
                manager,
                config.tools,
                original_root=state.source_root.resolve(strict=True),
            )
            diff = tools.build_diff()
            encoded = diff.encode("utf-8")
            returned = _truncate_utf8(encoded, config.tools.show_diff.max_output_bytes)
            print(
                json.dumps(
                    {
                        "task_id": str(state.task_id),
                        "phase": state.phase.value,
                        "generation": workspace.generation,
                        "bytes_total": len(encoded),
                        "bytes_returned": len(returned),
                        "truncated": len(returned) < len(encoded),
                        "diff": returned.decode("utf-8"),
                    },
                    separators=(",", ":"),
                )
            )
            return 0
    except (
        ConfigError,
        PathSecurityError,
        SnapshotError,
        TaskStateError,
        OSError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _review_task_audit(args: argparse.Namespace) -> int:
    state_root = (args.state_dir or _default_state_root()).absolute()
    try:
        summary = read_audit_summary(
            state_root / "audit" / f"{args.task_id}.jsonl",
            task_id=args.task_id,
        )
    except AuditReadError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(summary.model_dump_json())
    return 0


def _truncate_utf8(payload: bytes, limit: int) -> bytes:
    truncated = payload[:limit]
    while truncated:
        try:
            truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
            continue
        break
    return truncated


def _clean_tasks(args: argparse.Namespace) -> int:
    state_root = (args.state_dir or _default_state_root()).absolute()
    store = TaskStore(state_root / "tasks")
    if len(args.task_ids) != len(set(args.task_ids)):
        print(
            "error: clean task identifiers must not contain duplicates", file=sys.stderr
        )
        return 2
    try:
        candidates = tuple(
            inspect_cleanup_candidate(state_root, store.load(task_id))
            for task_id in args.task_ids
        )
        retained = tuple(candidate for candidate in candidates if candidate.retained)
        if retained and not args.include_retained:
            identifiers = ", ".join(str(candidate.task_id) for candidate in retained)
            raise TaskStateError(
                "selected tasks are retained and resumable; pass --include-retained "
                f"to delete them: {identifiers}"
            )
        minimum_age = args.older_than_days * 86_400
        eligible = tuple(
            candidate
            for candidate in candidates
            if minimum_age == 0 or candidate.age_seconds >= minimum_age
        )
        preview = {
            "selected": [candidate.model_dump(mode="json") for candidate in candidates],
            "eligible_task_ids": [str(candidate.task_id) for candidate in eligible],
            "bytes_total": sum(candidate.bytes_total for candidate in eligible),
        }
        print(json.dumps(preview, separators=(",", ":")), file=sys.stderr)
        if not eligible:
            print(
                json.dumps(
                    {"deleted_task_ids": [], "bytes_deleted": 0},
                    separators=(",", ":"),
                )
            )
            return 0
        if not args.yes:
            answer = input(f"Delete {len(eligible)} exact task target(s)? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                print(
                    json.dumps(
                        {"deleted_task_ids": [], "bytes_deleted": 0},
                        separators=(",", ":"),
                    )
                )
                return 0

        sessions: dict[UUID, TaskSession] = {}
        with ExitStack() as stack:
            for candidate in sorted(eligible, key=lambda item: item.task_id.hex):
                session = stack.enter_context(store.lease(candidate.task_id))
                if session.state.revision != candidate.revision:
                    raise TaskStateError(
                        f"task changed after cleanup preview: {candidate.task_id}"
                    )
                sessions[candidate.task_id] = session
            for candidate in eligible:
                session = sessions[candidate.task_id]
                remove_task_artifacts(state_root, candidate.task_id)
                store.delete_grants(candidate.task_id)
                store.delete_state(
                    candidate.task_id,
                    expected_revision=session.state.revision,
                )
        for candidate in eligible:
            with suppress(TaskStateError):
                store.delete_idle_lock(candidate.task_id)
        print(
            json.dumps(
                {
                    "deleted_task_ids": [
                        str(candidate.task_id) for candidate in eligible
                    ],
                    "bytes_deleted": sum(
                        candidate.bytes_total for candidate in eligible
                    ),
                },
                separators=(",", ":"),
            )
        )
        return 0
    except (EOFError, OSError, TaskStateError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _export_coding_patch(
    *,
    tools: CodingTools,
    destination: Path,
    audit: JsonlAuditSink,
    max_diff_bytes: int,
    recovered_after_failure: bool,
) -> str:
    diff = tools.build_diff()
    encoded_diff = diff.encode("utf-8")
    if not encoded_diff:
        raise ValueError("task has no pending patch to export")
    if len(encoded_diff) > max_diff_bytes:
        raise ControllerLimitError("final diff exceeds review output limit")
    bytes_written = tools.export_diff(destination)
    source_manifest = tools.source_manifest()
    current_manifest = tools.current_manifest()
    audit.append(
        PatchExportedEvent(
            task_id=tools.workspace.task_id,
            generation=tools.workspace.generation,
            bytes_written=bytes_written,
            sha256=hashlib.sha256(encoded_diff).hexdigest(),
            source_tree_sha256=source_manifest.tree_sha256,
            generation_tree_sha256=current_manifest.tree_sha256,
            recovered_after_failure=recovered_after_failure,
        )
    )
    return diff


def _try_recovery_export(
    *,
    tools: CodingTools | None,
    destination: Path,
    audit: JsonlAuditSink | None,
    max_diff_bytes: int,
) -> bool:
    if tools is None or audit is None or tools.workspace.generation == 0:
        return False
    try:
        _export_coding_patch(
            tools=tools,
            destination=destination,
            audit=audit,
            max_diff_bytes=max_diff_bytes,
            recovered_after_failure=True,
        )
    except (
        ControllerLimitError,
        PathSecurityError,
        SnapshotError,
        OSError,
        ValueError,
    ):
        print(
            "warning: completed disposable changes were discarded because recovery "
            "export failed",
            file=sys.stderr,
        )
        return False
    print(
        f"recovery patch exported to {destination} before discarding task state",
        file=sys.stderr,
    )
    return True
