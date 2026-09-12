# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path

import httpx
import pytest

from ulg import doctor
from ulg.cli import main
from ulg.config import load_config
from ulg.sandbox import DockerPreflightError
from ulg.sandbox.docker import SandboxExecutionError
from ulg.sandbox.preflight import DockerPreflightReport


@pytest.fixture
def healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.platform, "system", lambda: "Linux")
    monkeypatch.setattr(doctor.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        doctor.RootlessDockerPreflight,
        "check",
        lambda self: DockerPreflightReport(
            "unix:///run/user/1000/docker.sock", True, "2", "systemd", "/tmp/docker"
        ),
    )
    monkeypatch.setattr(
        doctor.RootlessDockerRunner, "verify_image", lambda self, endpoint: None
    )
    monkeypatch.setattr(
        doctor,
        "_model_checks",
        lambda settings: [
            doctor.Check("ollama", "pass", "reachable"),
            doctor.Check("model", "pass", "installed"),
        ],
    )


def test_ready_cli(healthy: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--config", "config/policy.example.toml", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ready"] is True
    assert len(result["checks"]) == 7


def test_missing_config_still_checks_docker(healthy: None, tmp_path: Path) -> None:
    checks = {c.name: c for c in doctor.diagnose(tmp_path / "missing")}
    assert checks["config"].status == "fail"
    assert checks["docker"].status == "pass"
    assert checks["model"].status == checks["runner"].status == "skip"


def test_docker_failure_is_actionable(
    healthy: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(self: object) -> None:
        raise DockerPreflightError("rootless Docker socket is unavailable")

    monkeypatch.setattr(doctor.RootlessDockerPreflight, "check", fail)
    assert main(["doctor", "--config", "config/policy.example.toml"]) == 2
    output = capsys.readouterr().out
    assert "ulg sandbox-preflight" in output
    assert "[SKIP] runner" in output


def test_runner_failure_suggests_exact_digest(
    healthy: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(self: object, endpoint: str) -> None:
        raise SandboxExecutionError("missing")

    monkeypatch.setattr(doctor.RootlessDockerRunner, "verify_image", fail)
    config = load_config(Path("config/policy.example.toml"))
    check = doctor.diagnose(Path("config/policy.example.toml"))[-1]
    assert check.status == "fail"
    assert config.sandbox.image in check.fix
    assert "--host unix:///run/user/1000/docker.sock pull" in check.fix


@pytest.mark.parametrize(
    "payload,status,expected",
    [
        ({"models": [{"name": "qwen3-coder:30b"}]}, 200, ["pass", "pass"]),
        ({"models": []}, 200, ["pass", "fail"]),
        ({"models": "bad"}, 200, ["fail", "skip"]),
        ({"models": []}, 302, ["fail", "skip"]),
        ({"models": []}, 500, ["fail", "skip"]),
    ],
)
def test_model_diagnostics(
    monkeypatch: pytest.MonkeyPatch, payload: object, status: int, expected: list[str]
) -> None:
    original = httpx.Client

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "http://127.0.0.1:11434/api/tags"
        return httpx.Response(status, json=payload)

    def client(**kwargs: object) -> httpx.Client:
        assert kwargs == {"timeout": 5, "trust_env": False, "follow_redirects": False}
        return original(transport=httpx.MockTransport(respond), follow_redirects=False)

    monkeypatch.setattr(doctor.httpx, "Client", client)
    settings = load_config(Path("config/policy.example.toml")).model
    assert [c.status for c in doctor._model_checks(settings)] == expected


def test_oversized_model_response(monkeypatch: pytest.MonkeyPatch) -> None:
    original = httpx.Client
    monkeypatch.setattr(
        doctor.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"x" * 101)
            )
        ),
    )
    settings = load_config(Path("config/policy.example.toml")).model.model_copy(
        update={"max_response_bytes": 100}
    )
    assert doctor._model_checks(settings)[0].status == "fail"
