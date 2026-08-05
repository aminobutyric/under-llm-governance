# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import json
import os
import stat
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

_FIELD_SEPARATOR = "\x1f"
_INFO_FORMAT = _FIELD_SEPARATOR.join(
    (
        "{{json .SecurityOptions}}",
        "{{.CgroupVersion}}",
        "{{.CgroupDriver}}",
        "{{json .DockerRootDir}}",
    )
)
_MAX_INFO_BYTES = 64 * 1024


class DockerPreflightError(RuntimeError):
    """Raised when the configured Docker daemon is unsuitable for sandboxing."""


@dataclass(frozen=True, slots=True)
class DockerPreflightReport:
    endpoint: str
    rootless: bool
    cgroup_version: str
    cgroup_driver: str
    docker_root_dir: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[bytes]]
SocketValidator = Callable[[Path, int], None]


class RootlessDockerPreflight:
    """Fail closed unless the dedicated user Docker socket is securely usable."""

    def __init__(
        self,
        *,
        docker_binary: Path = Path("/usr/bin/docker"),
        uid: int | None = None,
        command_runner: CommandRunner | None = None,
        socket_validator: SocketValidator | None = None,
    ) -> None:
        self._docker_binary = docker_binary
        self._uid = os.geteuid() if uid is None else uid
        self._command_runner = command_runner or _run_command
        self._socket_validator = socket_validator or _validate_socket

    def check(self) -> DockerPreflightReport:
        if self._uid == 0:
            raise DockerPreflightError("sandbox controller must not run as root")
        if not self._docker_binary.is_absolute():
            raise DockerPreflightError("Docker binary path must be absolute")

        socket_path = Path("/run/user") / str(self._uid) / "docker.sock"
        self._socket_validator(socket_path, self._uid)
        endpoint = f"unix://{socket_path}"
        command = (
            str(self._docker_binary),
            "--host",
            endpoint,
            "info",
            "--format",
            _INFO_FORMAT,
        )
        try:
            completed = self._command_runner(command)
        except (OSError, subprocess.SubprocessError) as error:
            raise DockerPreflightError("cannot query rootless Docker daemon") from error

        if completed.returncode != 0:
            raise DockerPreflightError("rootless Docker daemon is not accessible")
        if len(completed.stdout) > _MAX_INFO_BYTES:
            raise DockerPreflightError("Docker preflight response exceeds limit")

        return _validate_info(completed.stdout, endpoint=endpoint)


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5,
        env={"LC_ALL": "C", "PATH": os.defpath},
    )


def _validate_socket(socket_path: Path, uid: int) -> None:
    try:
        metadata = socket_path.lstat()
    except OSError as error:
        raise DockerPreflightError("rootless Docker socket is unavailable") from error
    if not stat.S_ISSOCK(metadata.st_mode):
        raise DockerPreflightError("rootless Docker endpoint is not a socket")
    if metadata.st_uid != uid:
        raise DockerPreflightError("rootless Docker socket has the wrong owner")


def _validate_info(payload: bytes, *, endpoint: str) -> DockerPreflightReport:
    try:
        fields = payload.decode("utf-8").rstrip("\n").split(_FIELD_SEPARATOR)
        if len(fields) != 4:
            raise ValueError
        raw_options, cgroup_version, cgroup_driver, raw_root = fields
        security_options = json.loads(raw_options)
        docker_root = json.loads(raw_root)
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise DockerPreflightError(
            "Docker returned malformed preflight data"
        ) from error

    if not isinstance(security_options, list) or not all(
        isinstance(option, str) for option in security_options
    ):
        raise DockerPreflightError("Docker returned invalid security options")
    if "name=rootless" not in security_options:
        raise DockerPreflightError("Docker daemon is not running in rootless mode")
    if cgroup_version != "2" or cgroup_driver != "systemd":
        raise DockerPreflightError(
            "rootless Docker requires cgroup v2 with the systemd driver"
        )
    if not isinstance(docker_root, str) or not Path(docker_root).is_absolute():
        raise DockerPreflightError("Docker returned an invalid data-root path")

    return DockerPreflightReport(
        endpoint=endpoint,
        rootless=True,
        cgroup_version=cgroup_version,
        cgroup_driver=cgroup_driver,
        docker_root_dir=docker_root,
    )
