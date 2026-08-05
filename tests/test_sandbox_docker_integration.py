# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ulg.config import load_config
from ulg.config.models import RecipeSettings, SandboxSettings
from ulg.sandbox import RootlessDockerRunner

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

    assert runner.run(recipe_name="python", workspace=tmp_path).ok
    assert runner.run(recipe_name="go", workspace=tmp_path).ok
    assert runner.run(recipe_name="javascript", workspace=tmp_path).ok


def test_network_host_authority_and_privilege_escalation_are_absent(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "containment.py",
        "import os, pathlib, socket\n"
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


def test_process_memory_environment_and_input_are_contained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    memory = runner.run(recipe_name="memory", workspace=tmp_path)
    contained_input = runner.run(recipe_name="input", workspace=tmp_path)

    assert fork.ok and "pids-bounded" in fork.output
    assert not memory.ok and memory.exit_code not in {None, 0}
    assert contained_input.ok and "input-read-only" in contained_input.output
    assert (tmp_path / "original.txt").read_text() == "unchanged\n"


def _runner(
    recipes: dict[str, RecipeSettings], **updates: object
) -> RootlessDockerRunner:
    config = load_config(Path("config/policy.example.toml"))
    payload = {**config.sandbox.model_dump(), **updates}
    settings = SandboxSettings.model_validate(payload)
    return RootlessDockerRunner(settings, recipes)


def _write(path: Path, content: str) -> None:
    path.write_text(content)


def _seal(root: Path) -> None:
    for path in root.rglob("*"):
        path.chmod(0o555 if path.is_dir() or os.access(path, os.X_OK) else 0o444)
    root.chmod(0o555)
