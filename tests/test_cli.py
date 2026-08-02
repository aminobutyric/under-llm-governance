# SPDX-License-Identifier: MPL-2.0

import json

from ulg.cli import main


def test_dry_run_cli(capsys: object) -> None:
    assert main(["dry-run"]) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    payload = json.loads(output)
    assert payload["action_type"] == "list_files"
    assert payload["decision"] == "allow"
    assert payload["executed"] is False
