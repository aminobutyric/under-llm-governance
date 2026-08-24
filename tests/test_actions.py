# SPDX-License-Identifier: MPL-2.0

from uuid import uuid4

import pytest
from pydantic import ValidationError

from ulg.actions import (
    ListFilesAction,
    RunTaskAction,
    action_json_schema,
    ollama_action_json_schema,
    parse_action,
    parse_action_json,
)


def test_unknown_action_field_is_rejected() -> None:
    payload = {
        "schema_version": 1,
        "type": "list_files",
        "task_id": uuid4(),
        "rationale": "inspect the project",
        "path": ".",
        "unexpected": True,
    }

    with pytest.raises(ValidationError):
        parse_action(payload)


@pytest.mark.parametrize("path", ["/etc/passwd", "bad\x00path", "../secret"])
def test_list_files_rejects_unsafe_path_shape(path: str) -> None:
    with pytest.raises(ValidationError):
        ListFilesAction(task_id=uuid4(), rationale="inspect", path=path)


def test_strict_action_accepts_uuid_from_json_representation() -> None:
    action = ListFilesAction(task_id=uuid4(), rationale="inspect", path=".")

    parsed = parse_action_json(action.model_dump_json())

    assert parsed == action


def test_ollama_schema_removes_non_authoritative_uuid_format_metadata() -> None:
    schema = ollama_action_json_schema()
    serialized = str(schema)

    assert "format" not in serialized
    assert "oneOf" not in serialized
    assert "$ref" not in serialized
    assert "action_id" not in serialized
    assert "run_task" not in schema["properties"]["type"]["enum"]  # type: ignore[index]
    assert "run_task" in str(action_json_schema())

    coding_schema = ollama_action_json_schema(
        include_run_task=True, recipe_names=("test", "lint")
    )
    assert "run_task" in coding_schema["properties"]["type"]["enum"]  # type: ignore[index]
    assert "recipe_name" in coding_schema["properties"]  # type: ignore[operator]
    assert coding_schema["properties"]["recipe_name"]["enum"] == [  # type: ignore[index]
        "test",
        "lint",
    ]


@pytest.mark.parametrize(
    "recipe_name",
    ["", "Test", "../test", "test task", "a" * 65],
)
def test_run_task_rejects_invalid_recipe_names(recipe_name: str) -> None:
    with pytest.raises(ValidationError):
        RunTaskAction(
            task_id=uuid4(),
            rationale="verify",
            recipe_name=recipe_name,
        )


def test_run_task_round_trip_has_no_command_surface() -> None:
    action = RunTaskAction(
        task_id=uuid4(),
        rationale="run trusted tests",
        recipe_name="python_test",
    )

    assert parse_action_json(action.model_dump_json()) == action
    with pytest.raises(ValidationError):
        parse_action(
            {
                **action.model_dump(),
                "argv": ["sh", "-c", "malicious"],
            }
        )
