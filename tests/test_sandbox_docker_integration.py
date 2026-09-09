# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ulg.audit import MemoryAuditSink, SandboxFinishedEvent
from ulg.config import load_config
from ulg.config.models import RecipeSettings, SandboxSettings
from ulg.sandbox import RootlessDockerPreflight, RootlessDockerRunner, SandboxResult

pytestmark = pytest.mark.skipif(
    os.environ.get("ULG_RUN_DOCKER_TESTS") != "1",
    reason="set ULG_RUN_DOCKER_TESTS=1 to run rootless Docker acceptance tests",
)


def test_python_go_and_javascript_checks_run_offline(tmp_path: Path) -> None:
    _write(tmp_path / "test_ok.py", "def test_ok():\n    assert 2 + 2 == 4\n")
    _write(tmp_path / "go.mod", "module example.test/phase3\n\ngo 1.19\n")
    _write(
        tmp_path / "main_test.go",
        'package phase3\n\nimport "testing"\n\nfunc TestOK(t *testing.T) {}\n',
    )
    _write(
        tmp_path / "ok.test.js",
        "const test = require('node:test');\n"
        "const assert = require('node:assert');\n"
        "test('ok', () => assert.equal(2 + 2, 4));\n",
    )
    _seal(tmp_path)
    runner = _runner(
        {
            "python": RecipeSettings(argv=("python", "-m", "pytest", "-q")),
            "go": RecipeSettings(argv=("go", "test", "./...")),
            "javascript": RecipeSettings(argv=("node", "--test")),
        }
    )

    for recipe in ("python", "go", "javascript"):
        result = runner.run(recipe_name=recipe, workspace=tmp_path)
        assert result.ok
        _assert_auditable(result)


def test_network_host_authority_and_privilege_escalation_are_absent(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "containment.py",
        "import os, pathlib, shutil, socket\n"
        "assert os.getuid() != 0\n"
        "status = pathlib.Path('/proc/self/status').read_text()\n"
        "assert 'CapEff:\\t0000000000000000' in status\n"
        "assert 'NoNewPrivs:\\t1' in status\n"
        "assert not pathlib.Path('/var/run/docker.sock').exists()\n"
        "assert not pathlib.Path('/host-marker').exists()\n"
        "assert not pathlib.Path('/dev/sda').exists()\n"
        "memory_max = pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip()\n"
        "assert memory_max == '536870912'\n"
        "assert pathlib.Path('/sys/fs/cgroup/pids.max').read_text().strip() == '128'\n"
        "cpu_quota = pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().split()[0]\n"
        "assert cpu_quota != 'max'\n"
        "assert shutil.which('curl') is None\n"
        "try:\n"
        "    socket.getaddrinfo('example.com', 443)\n"
        "except socket.gaierror:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('DNS reachable')\n"
        "sock = socket.socket(); sock.settimeout(0.2)\n"
        "try:\n"
        "    sock.connect(('127.0.0.1', 11434))\n"
        "except OSError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('localhost network reachable')\n"
        "try:\n"
        "    socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)\n"
        "except PermissionError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('raw socket capability available')\n",
    )
    _seal(tmp_path)
    runner = _runner({"containment": RecipeSettings(argv=("python", "containment.py"))})

    result = runner.run(recipe_name="containment", workspace=tmp_path)

    assert result.ok, result.output
    _assert_auditable(result)


def test_timeout_output_and_workspace_disk_are_bounded(tmp_path: Path) -> None:
    _write(tmp_path / "loop.py", "while True: pass\n")
    _write(
        tmp_path / "flood.py",
        "import os\nwhile True: os.write(1, b'x' * 65536)\n",
    )
    _write(
        tmp_path / "disk.py",
        "from pathlib import Path\n"
        "try:\n"
        "    Path('fill').write_bytes(b'x' * (32 * 1024 * 1024))\n"
        "except OSError:\n"
        "    print('bounded')\n"
        "else:\n"
        "    raise AssertionError('workspace tmpfs limit not enforced')\n",
    )
    _seal(tmp_path)
    runner = _runner(
        {
            "loop": RecipeSettings(argv=("python", "loop.py")),
            "flood": RecipeSettings(argv=("python", "flood.py")),
            "disk": RecipeSettings(argv=("python", "disk.py")),
        },
        wall_time_seconds=1,
        max_combined_output_bytes=4_096,
        workspace_tmpfs_bytes=16_777_216,
    )

    timeout = runner.run(recipe_name="loop", workspace=tmp_path)
    flood = runner.run(recipe_name="flood", workspace=tmp_path)
    disk = runner.run(recipe_name="disk", workspace=tmp_path)

    assert timeout.timed_out and timeout.error_code == "timeout"
    assert flood.output_truncated and flood.error_code == "output_limit"
    assert flood.output_bytes <= 65_536
    assert disk.ok and "bounded" in disk.output
    _assert_auditable(timeout)
    _assert_auditable(flood)
    _assert_auditable(disk)


def test_process_memory_environment_and_input_are_contained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container_uuid = UUID("11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr("ulg.sandbox.docker.uuid4", lambda: container_uuid)
    _write(tmp_path / "original.txt", "unchanged\n")
    _write(
        tmp_path / "fork.py",
        "import subprocess\n"
        "children = []\n"
        "try:\n"
        "    while True:\n"
        "        children.append(subprocess.Popen(['sleep', '30']))\n"
        "except OSError:\n"
        "    print('pids-bounded')\n"
        "finally:\n"
        "    for child in children: child.kill()\n",
    )
    _write(
        tmp_path / "detached.py",
        "import subprocess\n"
        "subprocess.Popen(['sleep', '30'], start_new_session=True)\n"
        "print('detached-child-started')\n",
    )
    _write(
        tmp_path / "memory.py",
        "chunks = []\nwhile True: chunks.append(bytearray(16 * 1024 * 1024))\n",
    )
    _write(
        tmp_path / "input.py",
        "import os, pathlib\n"
        "assert os.environ.get('ULG_TEST_SECRET') is None\n"
        "try:\n"
        "    pathlib.Path('/input/original.txt').write_text('changed')\n"
        "except OSError:\n"
        "    print('input-read-only')\n"
        "else:\n"
        "    raise AssertionError('input mount was writable')\n",
    )
    _seal(tmp_path)
    monkeypatch.setenv("ULG_TEST_SECRET", "must-not-enter-container")
    runner = _runner(
        {
            "fork": RecipeSettings(argv=("python", "fork.py")),
            "detached": RecipeSettings(argv=("python", "detached.py")),
            "memory": RecipeSettings(argv=("python", "memory.py")),
            "input": RecipeSettings(argv=("python", "input.py")),
        },
        memory_bytes=134_217_728,
        pids=32,
        tmpfs_bytes=16_777_216,
        workspace_tmpfs_bytes=33_554_432,
        wall_time_seconds=5,
    )

    fork = runner.run(recipe_name="fork", workspace=tmp_path)
    detached = runner.run(recipe_name="detached", workspace=tmp_path)
    endpoint = RootlessDockerPreflight().check().endpoint
    detached_container = subprocess.run(
        (
            "/usr/bin/docker",
            "--host",
            endpoint,
            "container",
            "inspect",
            f"ulg-{container_uuid.hex}",
        ),
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5,
    )
    memory = runner.run(recipe_name="memory", workspace=tmp_path)
    contained_input = runner.run(recipe_name="input", workspace=tmp_path)

    assert fork.ok and "pids-bounded" in fork.output
    assert detached.ok and "detached-child-started" in detached.output
    assert detached_container.returncode != 0
    assert not memory.ok and memory.exit_code not in {None, 0}
    assert contained_input.ok and "input-read-only" in contained_input.output
    assert (tmp_path / "original.txt").read_text() == "unchanged\n"
    for result in (fork, detached, memory, contained_input):
        _assert_auditable(result)


def test_git_hooks_and_package_lifecycle_scripts_are_not_implicitly_executed(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "test_safe.py", "def test_safe(): assert True\n")
    _write(
        tmp_path / "package.json",
        '{"scripts":{"preinstall":"touch /input/lifecycle-ran"}}\n',
    )
    _write(
        tmp_path / ".git" / "hooks" / "pre-commit",
        "#!/bin/sh\ntouch /input/git-hook-ran\n",
    )
    (tmp_path / ".git" / "hooks" / "pre-commit").chmod(0o755)
    _seal(tmp_path)
    runner = _runner({"test": RecipeSettings(argv=("python", "-m", "pytest", "-q"))})

    result = runner.run(recipe_name="test", workspace=tmp_path)

    assert result.ok, result.output
    assert not (tmp_path / "lifecycle-ran").exists()
    assert not (tmp_path / "git-hook-ran").exists()
    _assert_auditable(result)


def _runner(
    recipes: dict[str, RecipeSettings], **updates: object
) -> RootlessDockerRunner:
    config = load_config(Path("config/policy.example.toml"))
    payload = {**config.sandbox.model_dump(), **updates}
    settings = SandboxSettings.model_validate(payload)
    return RootlessDockerRunner(settings, recipes)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _seal(root: Path) -> None:
    for path in root.rglob("*"):
        path.chmod(0o555 if path.is_dir() or os.access(path, os.X_OK) else 0o444)
    root.chmod(0o555)


def _assert_auditable(result: SandboxResult) -> None:
    audit = MemoryAuditSink()
    audit.append(
        SandboxFinishedEvent(
            task_id=uuid4(),
            recipe_name=result.recipe_name,
            recipe_digest=result.recipe_digest,
            image_digest=result.image_digest,
            sandbox_profile_digest=result.sandbox_profile_digest,
            ok=result.ok,
            error_code=result.error_code,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            cancelled=result.cancelled,
            duration_ms=result.duration_ms,
            output_bytes=result.output_bytes,
            output_truncated=result.output_truncated,
        )
    )
    event = audit.events[0]
    assert event.event_type == "sandbox_finished"
    assert "output" not in event.model_dump()
