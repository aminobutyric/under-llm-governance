# SPDX-License-Identifier: MPL-2.0

from pathlib import Path
from uuid import uuid4

from ulg.actions import ListFilesAction, ReadFileAction, SearchTextAction
from ulg.config import load_config
from ulg.tools import ReadOnlyTools
from ulg.workspace import SecureRoot, SnapshotWorkspaceManager


def test_read_only_tools_are_bounded_and_recheck_secret_exclusions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "alpha.txt").write_text("alpha needle\nsecond line\n")
    (source / "beta.txt").write_text("beta")
    config = load_config(Path("config/policy.example.toml"))
    manager = SnapshotWorkspaceManager(tmp_path / "state", config.workspace)
    task_id = uuid4()
    workspace = manager.create(source=source, task_id=task_id)

    # Simulate a later workspace mutation trying to introduce a secret file.
    (workspace.root / ".env").write_text("TOKEN=secret")
    list_settings = config.tools.list_files.model_copy(update={"max_entries": 1})
    read_settings = config.tools.read_file.model_copy(update={"max_bytes": 4})

    with SecureRoot(workspace.root) as secure_root:
        tools = ReadOnlyTools(
            secure_root,
            manager.exclusion_policy,
            list_settings=list_settings,
            read_settings=read_settings,
            search_settings=config.tools.search_text,
        )

        listing = tools.list_files(
            ListFilesAction(task_id=task_id, rationale="list", path=".")
        )
        assert listing.ok is True
        assert listing.truncated is True
        assert len(listing.entries) == 1
        assert all(entry.path != ".env" for entry in listing.entries)

        read = tools.read_file(
            ReadFileAction(task_id=task_id, rationale="read", path="alpha.txt")
        )
        assert read.ok is True
        assert read.content == "alph"
        assert read.truncated is True
        assert read.bytes_read == 4

        secret = tools.read_file(
            ReadFileAction(task_id=task_id, rationale="read", path=".env")
        )
        assert secret.ok is False
        assert secret.error_code == "excluded_path"

        search_tools = ReadOnlyTools(
            secure_root,
            manager.exclusion_policy,
            list_settings=config.tools.list_files,
            read_settings=config.tools.read_file,
            search_settings=config.tools.search_text,
        )
        search = search_tools.search_text(
            SearchTextAction(
                task_id=task_id,
                rationale="search",
                path=".",
                query="needle",
            )
        )
        assert search.ok is True
        assert len(search.matches) == 1
        assert search.matches[0].path == "alpha.txt"
        assert search.matches[0].line_number == 1
