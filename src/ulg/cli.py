# SPDX-License-Identifier: MPL-2.0

import argparse
from collections.abc import Sequence
from uuid import uuid4

from ulg import __version__
from ulg.actions import ListFilesAction
from ulg.audit import MemoryAuditSink
from ulg.controller import Controller
from ulg.model import FakeModel
from ulg.policy import BaselinePolicy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ulg")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser(
        "dry-run", help="exercise model, schema, policy, and audit contracts"
    )
    dry_run.add_argument("--path", default=".")
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
    raise AssertionError("argparse accepted an unknown command")
