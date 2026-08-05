# SPDX-License-Identifier: MPL-2.0

import subprocess
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ulg.sandbox import DockerPreflightError, RootlessDockerPreflight
from ulg.tools import RunTaskResult

_DIGEST = "a" * 64


def _docker_info(
    *,
    security_options: str = '["name=seccomp,profile=builtin","name=rootless"]',
    cgroup_version: str = "2",
    cgroup_driver: str = "systemd",
) -> bytes:
    return (
        f"{security_options}\x1f{cgroup_version}\x1f{cgroup_driver}"
        '\x1f"/home/user/.local/share/docker"\n'
    ).encode()


def _completed(
    stdout: bytes, *, returncode: int = 0
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=b"")


def test_rootless_docker_preflight_accepts_required_daemon() -> None:
    uid = 1234
    commands: list[Sequence[str]] = []

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return _completed(_docker_info())

    report = RootlessDockerPreflight(
        uid=uid,
        docker_binary=Path("/usr/bin/docker"),
        command_runner=run,
        socket_validator=lambda _path, _uid: None,
    ).check()

    assert report.rootless is True
    assert report.cgroup_version == "2"
    assert commands[0][1:3] == (
        "--host",
        f"unix:///run/user/{uid}/docker.sock",
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_docker_info(security_options='["name=seccomp"]'), "not running in rootless"),
        (_docker_info(cgroup_version="1"), "requires cgroup v2"),
        (_docker_info(cgroup_driver="none"), "requires cgroup v2"),
        (b"malformed", "malformed"),
    ],
)
def test_rootless_docker_preflight_rejects_unsuitable_daemon(
    payload: bytes,
    message: str,
) -> None:
    uid = 1234
    with pytest.raises(DockerPreflightError, match=message):
        RootlessDockerPreflight(
            uid=uid,
            docker_binary=Path("/usr/bin/docker"),
            command_runner=lambda _: _completed(payload),
            socket_validator=lambda _path, _uid: None,
        ).check()


def test_successful_run_task_result_is_strict_and_bounded() -> None:
    result = RunTaskResult(
        action_id=uuid4(),
        ok=True,
        recipe_name="python_test",
        recipe_digest=_DIGEST,
        image_digest=f"sha256:{_DIGEST}",
        sandbox_profile_digest=_DIGEST,
        exit_code=0,
        duration_ms=25,
        output="passed\n",
        output_bytes=7,
    )

    assert result.type == "run_task_result"
    assert result.truncated is False


def test_truncated_run_task_result_tracks_observed_bytes() -> None:
    result = RunTaskResult(
        action_id=uuid4(),
        ok=False,
        error_code="output_limit",
        truncated=True,
        recipe_name="python_test",
        recipe_digest=_DIGEST,
        image_digest=f"sha256:{_DIGEST}",
        sandbox_profile_digest=_DIGEST,
        exit_code=1,
        duration_ms=30,
        output="partial",
        output_bytes=1_000_000,
    )

    assert result.output == "partial"
    assert result.output_bytes > len(result.output.encode())


@pytest.mark.parametrize(
    "updates",
    [
        {"ok": True, "exit_code": 1},
        {"ok": True, "timed_out": True},
        {"ok": False, "exit_code": 0, "error_code": None},
        {"timed_out": True, "cancelled": True},
        {"output": "too long", "output_bytes": 1},
    ],
)
def test_run_task_result_rejects_inconsistent_outcomes(
    updates: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "action_id": uuid4(),
        "ok": False,
        "error_code": "sandbox_failed",
        "recipe_name": "python_test",
        "recipe_digest": _DIGEST,
        "image_digest": f"sha256:{_DIGEST}",
        "sandbox_profile_digest": _DIGEST,
        "exit_code": 1,
        "duration_ms": 10,
        "output": "",
        "output_bytes": 0,
    }
    payload.update(updates)

    with pytest.raises(ValidationError):
        RunTaskResult.model_validate(payload)


def test_run_task_result_rejects_raw_or_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RunTaskResult.model_validate(
            {
                "action_id": uuid4(),
                "ok": False,
                "error_code": "sandbox_failed",
                "recipe_name": "test",
                "recipe_digest": _DIGEST,
                "image_digest": f"sha256:{_DIGEST}",
                "sandbox_profile_digest": _DIGEST,
                "exit_code": 1,
                "duration_ms": 10,
                "output": "",
                "output_bytes": 0,
                "raw_environment": {"TOKEN": "secret"},
            }
        )
