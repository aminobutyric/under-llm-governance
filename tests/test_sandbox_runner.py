# SPDX-License-Identifier: MPL-2.0

from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

from ulg.config import load_config
from ulg.sandbox.docker import RootlessDockerRunner, SandboxExecutionError


def test_runner_command_has_fixed_least_privilege_profile(tmp_path: Path) -> None:
    config = load_config(Path("config/policy.example.toml"))
    runner = RootlessDockerRunner(config.sandbox, config.recipes)

    command = runner._build_command(
        endpoint="unix:///run/user/1001/docker.sock",
        container_name="ulg-test",
        workspace=tmp_path,
        argv=("python", "-m", "pytest", "-q"),
    )

    assert command[:4] == (
        "/usr/bin/docker",
        "--host",
        "unix:///run/user/1001/docker.sock",
        "run",
    )
    assert _option(command, "--network") == "none"
    assert _option(command, "--cap-drop") == "ALL"
    assert _option(command, "--user") == "65532:65532"
    assert _option(command, "--pids-limit") == "128"
    assert _option(command, "--pull") == "never"
    assert "--read-only" in command
    assert "--privileged" not in command
    assert "--device" not in command
    assert "--pid" not in command
    assert "--volume" not in command
    assert "/var/run/docker.sock" not in " ".join(command)
    assert command[-4:] == ("python", "-m", "pytest", "-q")
    assert command[-5] == config.sandbox.image_digest


def test_runner_rejects_unknown_recipe_and_unsafe_mount_path(tmp_path: Path) -> None:
    config = load_config(Path("config/policy.example.toml"))
    runner = RootlessDockerRunner(config.sandbox, config.recipes)

    with pytest.raises(SandboxExecutionError, match="trusted configuration"):
        runner.run(recipe_name="unknown", workspace=tmp_path)

    unsafe = tmp_path / "contains,comma"
    unsafe.mkdir()
    with pytest.raises(SandboxExecutionError, match="cannot be mounted safely"):
        runner.run(recipe_name="test", workspace=unsafe)


def test_recipe_and_profile_digests_are_deterministic() -> None:
    config = load_config(Path("config/policy.example.toml"))
    first = RootlessDockerRunner(config.sandbox, config.recipes)
    second = RootlessDockerRunner(config.sandbox, config.recipes)

    assert first._profile_payload() == second._profile_payload()


def test_keyboard_interrupt_returns_cancelled_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(Path("config/policy.example.toml"))
    runner = RootlessDockerRunner(config.sandbox, config.recipes)
    process = _InterruptedProcess()
    monkeypatch.setattr("ulg.sandbox.docker.subprocess.Popen", lambda *a, **k: process)
    monkeypatch.setattr(
        "ulg.sandbox.docker.selectors.DefaultSelector", _InterruptSelector
    )
    monkeypatch.setattr(runner, "_terminate", lambda *a, **k: process.kill())
    monkeypatch.setattr(runner, "_remove_container", lambda *a, **k: None)

    result = runner._execute(
        ("docker", "run"),
        endpoint="unix:///run/user/1001/docker.sock",
        container_name="ulg-test",
        recipe_name="test",
        recipe_digest="a" * 64,
        profile_digest="b" * 64,
    )

    assert result.cancelled is True
    assert result.error_code == "cancelled"
    assert result.exit_code is None


def _option(command: tuple[str, ...], name: str) -> str:
    return command[command.index(name) + 1]


class _InterruptedProcess:
    def __init__(self) -> None:
        self.stdout = object()
        self.returncode: int | None = None
        self.pid = 1234

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: int) -> int:
        del timeout
        if self.returncode is None:
            raise AssertionError("process was not terminated")
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


class _InterruptSelector:
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def register(self, fileobj: object, events: int) -> None:
        del fileobj, events

    def select(self, timeout: float) -> list[tuple[object, int]]:
        del timeout
        raise KeyboardInterrupt

    def close(self) -> None:
        pass
