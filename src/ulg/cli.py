# SPDX-License-Identifier: MPL-2.0

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal
from uuid import uuid4

from ulg import __version__
from ulg.actions import ListFilesAction
from ulg.audit import (
    JsonlAuditSink,
    MemoryAuditSink,
    PatchExportedEvent,
    SandboxFinishedEvent,
    TaskLifecycleEvent,
    WorkspaceDiscardedEvent,
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
from ulg.tools import CodingTools, ReadOnlyTools
from ulg.workspace import (
    PathSecurityError,
    SecureRoot,
    SnapshotError,
    SnapshotWorkspaceManager,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ulg")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser(
        "dry-run", help="exercise model, schema, policy, and audit contracts"
    )
    dry_run.add_argument("--path", default=".")

    subparsers.add_parser(
        "sandbox-preflight",
        help="verify that the local Docker daemon meets sandbox requirements",
    )

    sandbox_run = subparsers.add_parser(
        "sandbox-run",
        help="run one trusted recipe in a disposable offline sandbox",
    )
    sandbox_run.add_argument("--workspace", required=True, type=Path)
    sandbox_run.add_argument("--recipe", required=True)
    sandbox_run.add_argument(
        "--config",
        type=Path,
        default=Path("config/policy.example.toml"),
    )
    sandbox_run.add_argument("--state-dir", type=Path, default=None)

    inspect = subparsers.add_parser(
        "inspect", help="inspect a disposable read-only snapshot with Ollama"
    )
    inspect.add_argument("--workspace", required=True, type=Path)
    inspect.add_argument("--task", required=True)
    inspect.add_argument(
        "--model",
        default=None,
        help="override the trusted local model name from the policy file",
    )
    inspect.add_argument(
        "--config",
        type=Path,
        default=Path("config/policy.example.toml"),
    )
    inspect.add_argument("--state-dir", type=Path, default=None)

    run = subparsers.add_parser(
        "run", help="produce a reviewed patch in a disposable workspace"
    )
    run.add_argument("--workspace", required=True, type=Path)
    run.add_argument("--task", required=True)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--model", default=None)
    run.add_argument(
        "--config",
        type=Path,
        default=Path("config/policy.example.toml"),
    )
    run.add_argument("--state-dir", type=Path, default=None)
    return parser


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
            print(f"error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(report.to_dict(), separators=(",", ":")))
        return 0
    if args.command == "sandbox-run":
        return _run_sandbox_recipe(args)
    if args.command == "inspect":
        return _run_inspect(args)
    if args.command == "run":
        return _run_coding(args)
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
        print(f"error: {error}", file=sys.stderr)
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
        print(f"error: {error}", file=sys.stderr)
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
    state_root = args.state_dir or _default_state_root()
    workspace = None
    model = None
    tools: CodingTools | None = None
    audit: JsonlAuditSink | None = None
    patch_exported = False
    cleanup_reason: Literal["completed", "failed", "cancelled"] = "failed"
    max_diff_bytes = 0
    try:
        _require_state_outside_workspace(args.workspace, state_root)
        config = load_config(args.config)
        max_diff_bytes = config.tools.show_diff.max_output_bytes
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
        tools = CodingTools(
            workspace,
            manager,
            config.tools,
            original_root=args.workspace,
            sandbox=RootlessDockerRunner(config.sandbox, config.recipes),
        )
        controller = ReadOnlyController(
            model=model,
            policy=BaselinePolicy(
                config.tools.apply_patch,
                config.tools.run_task,
            ),
            tools=tools,
            audit=audit,
            settings=config.task,
        )
        report = controller.run(task_id=task_id, task=args.task)
        diff = _export_coding_patch(
            tools=tools,
            destination=args.output,
            audit=audit,
            max_diff_bytes=max_diff_bytes,
            recovered_after_failure=False,
        )
        patch_exported = True
        cleanup_reason = "completed"
        print(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "diff": diff,
                    "exported_patch": str(args.output),
                },
                separators=(",", ":"),
            )
        )
        return 0
    except KeyboardInterrupt:
        cleanup_reason = "cancelled"
        patch_exported = _try_recovery_export(
            tools=tools,
            destination=args.output,
            audit=audit,
            max_diff_bytes=max_diff_bytes,
        )
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
        cleanup_reason = "failed"
        patch_exported = _try_recovery_export(
            tools=tools,
            destination=args.output,
            audit=audit,
            max_diff_bytes=max_diff_bytes,
        )
        print(f"error: {error}", file=sys.stderr)
        return 2
    finally:
        try:
            if model is not None:
                model.close()
        except Exception as error:
            print(f"warning: model client close failed: {error}", file=sys.stderr)
        finally:
            if workspace is not None:
                final_workspace = tools.workspace if tools is not None else workspace
                try:
                    if audit is not None:
                        audit.append(
                            WorkspaceDiscardedEvent(
                                task_id=task_id,
                                generation=final_workspace.generation,
                                reason_code=cleanup_reason,
                                patch_exported=patch_exported,
                            )
                        )
                finally:
                    manager.discard(final_workspace)


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
