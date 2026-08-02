# SPDX-License-Identifier: MPL-2.0

from uuid import uuid4

import pytest
from pydantic import ValidationError

from ulg.actions import (
    ListFilesAction,
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
