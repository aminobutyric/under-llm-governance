# SPDX-License-Identifier: MPL-2.0

from uuid import uuid4

import pytest
from pydantic import ValidationError

from ulg.actions import ListFilesAction, parse_action


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
