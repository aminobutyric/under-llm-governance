# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import stat
import subprocess
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from ulg.config.models import RecipeSettings, SandboxSettings
from ulg.sandbox.base import SandboxResult
from ulg.sandbox.preflight import DockerPreflightError, RootlessDockerPreflight

_DOCKER_BINARY = Path("/usr/bin/docker")
_READ_CHUNK_BYTES = 64 * 1024
_DOCKER_CONTROL_TIMEOUT_SECONDS = 5


class SandboxExecutionError(RuntimeError):
    """The trusted sandbox runner could not safely start an execution."""


class RootlessDockerRunner:
    """Run fixed recipes with a non-negotiable, offline Docker profile."""

    def __init__(
        self,
        settings: SandboxSettings,
        recipes: Mapping[str, RecipeSettings],
        *,
        docker_binary: Path = _DOCKER_BINARY,
    ) -> None:
        self._settings = settings
        self._recipes = dict(recipes)
        self._docker_binary = docker_binary

    def run(self, *, recipe_name: str, workspace: Path) -> SandboxResult:
        recipe = self._recipes.get(recipe_name)
        if recipe is None:
            raise SandboxExecutionError(
                "recipe is not present in trusted configuration"
            )
        workspace = self._validate_workspace(workspace)
        try:
            preflight = RootlessDockerPreflight(
                docker_binary=self._docker_binary
            ).check()
        except DockerPreflightError as error:
            raise SandboxExecutionError("Docker preflight failed") from error
        self._verify_image(preflight.endpoint)

        recipe_digest = _sha256_json({"name": recipe_name, "argv": list(recipe.argv)})
        profile_digest = _sha256_json(self._profile_payload())
        container_name = f"ulg-{uuid4().hex}"
        command = self._build_command(
            endpoint=preflight.endpoint,
            container_name=container_name,
            workspace=workspace,
            argv=recipe.argv,
        )
        return self._execute(
            command,
            endpoint=preflight.endpoint,
            container_name=container_name,
            recipe_name=recipe_name,
            recipe_digest=recipe_digest,
            profile_digest=profile_digest,
        )

    def _validate_workspace(self, workspace: Path) -> Path:
        if not workspace.is_absolute():
            raise SandboxExecutionError("sandbox workspace path must be absolute")
        if any(character in str(workspace) for character in (",", "\n", "\x00")):
            raise SandboxExecutionError(
                "sandbox workspace path cannot be mounted safely"
            )
        try:
            metadata = workspace.lstat()
        except OSError as error:
            raise SandboxExecutionError("sandbox workspace is unavailable") from error
        if not stat.S_ISDIR(metadata.st_mode):
            raise SandboxExecutionError("sandbox workspace must be a directory")
        if metadata.st_uid != os.geteuid():
            raise SandboxExecutionError("sandbox workspace has the wrong owner")
        return workspace

    def _verify_image(self, endpoint: str) -> None:
        command = (
            str(self._docker_binary),
            "--host",
            endpoint,
            "image",
            "inspect",
            self._settings.image,
            "--format",
            "{{.Id}}",
        )
        try:
            completed = subprocess.run(
                command,
                check=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=_DOCKER_CONTROL_TIMEOUT_SECONDS,
                env=_docker_environment(),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SandboxExecutionError(
                "cannot inspect trusted runner image"
            ) from error
        observed = completed.stdout.decode("ascii", errors="replace").strip()
        if completed.returncode != 0 or observed != self._settings.image_digest:
            raise SandboxExecutionError("trusted runner image digest does not match")

    def _build_command(
        self,
        *,
        endpoint: str,
        container_name: str,
        workspace: Path,
        argv: Sequence[str],
    ) -> tuple[str, ...]:
        settings = self._settings
        input_mount = (
            f"type=bind,src={workspace},dst=/input,readonly,bind-propagation=rprivate"
        )
        workspace_tmpfs = (
            "rw,exec,nosuid,nodev,mode=700,"
            f"uid={settings.container_uid},gid={settings.container_gid},"
            f"size={settings.workspace_tmpfs_bytes}"
        )
        temporary_tmpfs = f"rw,exec,nosuid,nodev,mode=1777,size={settings.tmpfs_bytes}"
        return (
            str(self._docker_binary),
            "--host",
            endpoint,
            "run",
            "--rm",
            "--pull",
            "never",
            "--name",
            container_name,
            "--hostname",
            "ulg-sandbox",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--security-opt",
            "seccomp=builtin",
            "--read-only",
            "--user",
            f"{settings.container_uid}:{settings.container_gid}",
            "--pids-limit",
            str(settings.pids),
            "--memory",
            str(settings.memory_bytes),
            "--memory-swap",
            str(settings.memory_bytes),
            "--cpus",
            str(settings.cpus),
            "--ipc",
            "none",
            "--cgroupns",
            "private",
            "--init",
            "--log-driver",
            "none",
            "--mount",
            input_mount,
            "--tmpfs",
            f"/workspace:{workspace_tmpfs}",
            "--tmpfs",
            f"/tmp:{temporary_tmpfs}",
            "--workdir",
            "/workspace",
            "--env",
            "HOME=/tmp/home",
            "--env",
            "LANG=C.UTF-8",
            "--env",
            "LC_ALL=C.UTF-8",
            "--env",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONPYCACHEPREFIX=/tmp/pycache",
            "--env",
            "XDG_CACHE_HOME=/tmp/cache",
            "--env",
            "GOCACHE=/tmp/go-cache",
            "--env",
            "GOMODCACHE=/tmp/go-mod-cache",
            self._settings.image_digest,
            *argv,
        )

    def _execute(
        self,
        command: Sequence[str],
        *,
        endpoint: str,
        container_name: str,
        recipe_name: str,
        recipe_digest: str,
        profile_digest: str,
    ) -> SandboxResult:
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=_docker_environment(),
            )
        except OSError as error:
            raise SandboxExecutionError("cannot start Docker client") from error
        if process.stdout is None:
            self._terminate(process, endpoint=endpoint, container_name=container_name)
            raise SandboxExecutionError("Docker client output pipe is unavailable")

        captured = bytearray()
        observed_bytes = 0
        timed_out = False
        cancelled = False
        output_limited = False
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = started + self._settings.wall_time_seconds
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    self._terminate(
                        process, endpoint=endpoint, container_name=container_name
                    )
                    break
                events = selector.select(min(remaining, 0.1))
                for key, _ in events:
                    chunk = os.read(key.fd, _READ_CHUNK_BYTES)
                    if not chunk:
                        selector.unregister(process.stdout)
                        break
                    observed_bytes += len(chunk)
                    available = self._settings.max_combined_output_bytes - len(captured)
                    if available > 0:
                        captured.extend(chunk[:available])
                    if observed_bytes > self._settings.max_combined_output_bytes:
                        output_limited = True
                        self._terminate(
                            process, endpoint=endpoint, container_name=container_name
                        )
                        break
                if timed_out or output_limited:
                    break
                if process.poll() is not None and not selector.get_map():
                    break
        except KeyboardInterrupt:
            cancelled = True
            self._terminate(process, endpoint=endpoint, container_name=container_name)
        finally:
            selector.close()
            try:
                process.wait(timeout=_DOCKER_CONTROL_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self._kill_client(process)
            self._remove_container(endpoint, container_name)

        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        exit_code = process.returncode
        if timed_out:
            error_code = "timeout"
            exit_code = None
        elif cancelled:
            error_code = "cancelled"
            exit_code = None
        elif output_limited:
            error_code = "output_limit"
            exit_code = None
        elif exit_code == 0:
            error_code = None
        elif exit_code in {125, 126, 127, None}:
            error_code = "sandbox_failed"
        else:
            error_code = "command_failed"

        output = _safe_output(bytes(captured), observed_bytes)
        truncated = output_limited or len(output.encode("utf-8")) < observed_bytes
        return SandboxResult(
            recipe_name=recipe_name,
            recipe_digest=recipe_digest,
            image_digest=self._settings.image_digest,
            sandbox_profile_digest=profile_digest,
            ok=error_code is None,
            error_code=error_code,
            exit_code=exit_code,
            timed_out=timed_out,
            cancelled=cancelled,
            duration_ms=duration_ms,
            output=output,
            output_bytes=observed_bytes,
            output_truncated=truncated,
        )

    def _terminate(
        self,
        process: subprocess.Popen[bytes],
        *,
        endpoint: str,
        container_name: str,
    ) -> None:
        _docker_control(self._docker_binary, endpoint, "kill", container_name)
        self._kill_client(process)

    @staticmethod
    def _kill_client(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)

    def _remove_container(self, endpoint: str, container_name: str) -> None:
        _docker_control(self._docker_binary, endpoint, "rm", "--force", container_name)

    def _profile_payload(self) -> dict[str, object]:
        settings = self._settings
        return {
            "backend": settings.backend,
            "image_digest": settings.image_digest,
            "container_uid": settings.container_uid,
            "container_gid": settings.container_gid,
            "network": settings.network,
            "read_only_root": settings.read_only_root,
            "drop_capabilities": settings.drop_capabilities,
            "no_new_privileges": settings.no_new_privileges,
            "memory_bytes": settings.memory_bytes,
            "cpus": settings.cpus,
            "pids": settings.pids,
            "wall_time_seconds": settings.wall_time_seconds,
            "max_combined_output_bytes": settings.max_combined_output_bytes,
            "tmpfs_bytes": settings.tmpfs_bytes,
            "workspace_tmpfs_bytes": settings.workspace_tmpfs_bytes,
        }


def _docker_control(docker_binary: Path, endpoint: str, *arguments: str) -> None:
    with suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            (str(docker_binary), "--host", endpoint, *arguments),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_DOCKER_CONTROL_TIMEOUT_SECONDS,
            env=_docker_environment(),
        )


def _docker_environment() -> dict[str, str]:
    return {"LC_ALL": "C", "PATH": os.defpath}


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_output(payload: bytes, observed_bytes: int) -> str:
    decoded = payload.decode("utf-8", errors="replace")
    encoded = decoded.encode("utf-8")[:observed_bytes]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return ""
