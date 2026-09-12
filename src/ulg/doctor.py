# SPDX-License-Identifier: MPL-2.0
"""Read-only setup diagnostics. Never install, pull images, or run model inference."""

import json
import platform
import shlex
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import httpx

from ulg.config import ConfigError, load_config
from ulg.config.models import ModelSettings
from ulg.sandbox import DockerPreflightError, RootlessDockerPreflight
from ulg.sandbox.docker import RootlessDockerRunner, SandboxExecutionError


@dataclass(frozen=True)
class Check:
    name: str
    status: Literal["pass", "fail", "skip"]
    message: str
    fix: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _model_checks(settings: ModelSettings) -> list[Check]:
    try:
        with (
            httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client,
            client.stream(
                "GET", settings.endpoint.rstrip("/") + "/api/tags"
            ) as response,
        ):
            response.raise_for_status()
            payload = bytearray()
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > min(settings.max_response_bytes, 1_048_576):
                    raise ValueError("response too large")
        data = json.loads(payload)
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise ValueError("invalid model list")
        names: set[str] = set()
        for model in data["models"]:
            if not isinstance(model, dict) or not isinstance(model.get("name"), str):
                raise ValueError("invalid model entry")
            names.add(model["name"])
    except (httpx.HTTPError, ValueError):
        return [
            Check(
                "ollama",
                "fail",
                "Cannot read a valid local Ollama model list.",
                "Start Ollama (ollama serve) and check the policy endpoint.",
            ),
            Check("model", "skip", "Requires a reachable Ollama server."),
        ]
    expected = settings.name if ":" in settings.name else settings.name + ":latest"
    installed = settings.name in names or expected in names
    return [
        Check("ollama", "pass", "Local Ollama API is reachable."),
        Check(
            "model",
            "pass" if installed else "fail",
            f"{settings.name}: {'installed' if installed else 'not installed'}.",
            ""
            if installed
            else f"OLLAMA_HOST={shlex.quote(settings.endpoint)} "
            f"ollama pull {shlex.quote(settings.name)}",
        ),
    ]


def diagnose(config_path: Path) -> list[Check]:
    supported = platform.system() == "Linux" and platform.machine() in {
        "x86_64",
        "amd64",
    }
    checks = [
        Check(
            "platform",
            "pass" if supported else "fail",
            "Beta requires Linux amd64.",
            "" if supported else "Use a Linux amd64 host.",
        ),
        Check(
            "python",
            "pass" if (3, 11) <= sys.version_info[:2] <= (3, 13) else "fail",
            platform.python_version(),
            ""
            if (3, 11) <= sys.version_info[:2] <= (3, 13)
            else "Install Warrant with Python 3.11-3.13.",
        ),
    ]
    try:
        config = load_config(config_path)
    except ConfigError:
        config = None
        checks.append(
            Check(
                "config",
                "fail",
                "Trusted policy is missing or invalid.",
                "Run ulg init for first setup; otherwise correct your policy "
                "or pass --config PATH.",
            )
        )
        checks.extend(
            [
                Check("ollama", "skip", "Requires valid configuration."),
                Check("model", "skip", "Requires valid configuration."),
            ]
        )
    else:
        assert config is not None
        checks.append(Check("config", "pass", "Trusted policy validated."))
        checks.extend(_model_checks(config.model))
    try:
        report = RootlessDockerPreflight().check()
    except DockerPreflightError as error:
        checks.append(
            Check(
                "docker",
                "fail",
                str(error),
                "Configure rootless Docker with cgroup v2/systemd; "
                "run ulg sandbox-preflight.",
            )
        )
        checks.append(Check("runner", "skip", "Requires Docker preflight to pass."))
    else:
        checks.append(
            Check("docker", "pass", "Rootless Docker with cgroup v2/systemd.")
        )
        if config is None:
            checks.append(Check("runner", "skip", "Requires valid configuration."))
        else:
            try:
                RootlessDockerRunner(config.sandbox, config.recipes).verify_image(
                    report.endpoint
                )
            except SandboxExecutionError:
                checks.append(
                    Check(
                        "runner",
                        "fail",
                        "Configured runner digest is unavailable locally.",
                        f"docker --host {shlex.quote(report.endpoint)} "
                        f"pull {shlex.quote(config.sandbox.image)}",
                    )
                )
            else:
                checks.append(
                    Check(
                        "runner",
                        "pass",
                        "Configured immutable runner digest is present.",
                    )
                )
    return checks
