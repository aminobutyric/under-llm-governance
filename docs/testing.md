# Testing through the Phase 4 durable workflow

This guide verifies every implemented user path through Phase 4. Run commands
from the repository root unless a section explicitly says they work anywhere.

## 1. Prerequisites

- Linux with Python 3.11 or newer and `uv`.
- Rootless Docker for Phase 3 tests.
- A running local Ollama server and an installed model for Phase 1–2 manual
  tests.

Prepare reusable paths:

```console
export ULG_REPO=/home/amin-mth/Projects/Personal/under-llm-governance
cd "$ULG_REPO"
uv sync --frozen
uv run --frozen ulg init
export ULG_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/ulg/policy.toml"
```

Check Ollama models before choosing `--model`:

```console
ollama list
```

A smaller workspace reduces prompt context. A smaller model is still necessary
if the selected model's weights exceed available GPU or system memory.

## 2. Python release gate

```console
uv lock --check
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy src
uv run --frozen pytest
uv export --frozen --no-dev --no-emit-project \
  --output-file /tmp/ulg-runtime-requirements.txt
uv run --frozen pip-audit \
  --requirement /tmp/ulg-runtime-requirements.txt --disable-pip
```

The normal pytest run skips live Docker tests unless explicitly enabled.

## 3. Live rootless-Docker acceptance gate

Verify the daemon first:

```console
uv run --frozen ulg sandbox-preflight
```

Expected fields include `"rootless":true`, `"cgroup_version":"2"`, and
`"cgroup_driver":"systemd"`.

Read and pull the exact digest-qualified runner from the initialized policy:

```console
runner_ref="$(python -c 'import tomllib,pathlib; print(tomllib.loads((pathlib.Path.home()/".config/ulg/policy.toml").read_text())["sandbox"]["image"])')"
docker pull "$runner_ref"
docker image inspect "$runner_ref" --format '{{json .RepoDigests}}'
```

The reported repository digests must contain the exact `sandbox.image` value.
Release also requires proving that the same reference can be pulled from GHCR
on a clean machine. Reviewing and changing that reference is a trusted-operator
action.

Run the adversarial acceptance suite:

```console
ULG_RUN_DOCKER_TESTS=1 uv run --frozen pytest -q \
  tests/test_sandbox_docker_integration.py
```

It verifies representative Python, Go, and JavaScript checks plus network,
raw-socket, capability, device, cgroup, timeout, output, disk, PID, memory,
environment, input-mount, and original-directory containment.

Confirm cleanup:

```console
docker ps --all --filter 'name=ulg-' \
  --format '{{.Names}} {{.Status}}'
```

No rows should remain.

## 4. Phase 0 contract smoke test

```console
uv run --frozen ulg dry-run
```

Expected JSON includes `"decision":"allow"` and `"executed":false`.

## 5. Phase 1 inspection on a small directory

Create an intentionally small project:

```console
small_project="$(mktemp -d)"
printf '# Tiny project\n' > "$small_project/README.md"
printf 'def add(a, b):\n    return a + b\n' > "$small_project/app.py"
```

Run from any directory while locating ULG explicitly:

```console
uv run --project "$ULG_REPO" --frozen ulg inspect \
  --workspace "$small_project" \
  --config "$ULG_CONFIG" \
  --task "Explain this project and cite the files you read" \
  --model qwen3:14b
```

Confirm the report completes, cites files actually read, and leaves both source
files unchanged.

## 6. Phase 2 disposable editing and patch export

Use another small source directory and a new output path:

```console
edit_root="$(mktemp -d)"
mkdir "$edit_root/project"
printf 'def greet():\n    return "hello"\n' > "$edit_root/project/app.py"
```

```console
uv run --project "$ULG_REPO" --frozen ulg run \
  --workspace "$edit_root/project" \
  --config "$ULG_CONFIG" \
  --task "Change greet so it returns hello world" \
  --output "$edit_root/change.patch" \
  --model qwen3:14b
```

Inspect the source and artifact:

```console
cat "$edit_root/project/app.py"
cat "$edit_root/change.patch"
```

The original `app.py` must still return `"hello"`. Only the new patch artifact
should contain the proposed change.

## 7. Phase 3 operator smoke tests

These fixtures have no network dependency:

```console
uv run --project "$ULG_REPO" --frozen ulg sandbox-run \
  --workspace "$ULG_REPO/testdata/phase3/python" \
  --config "$ULG_CONFIG" \
  --recipe test

uv run --project "$ULG_REPO" --frozen ulg sandbox-run \
  --workspace "$ULG_REPO/testdata/phase3/go" \
  --config "$ULG_CONFIG" \
  --recipe go_test

uv run --project "$ULG_REPO" --frozen ulg sandbox-run \
  --workspace "$ULG_REPO/testdata/phase3/javascript" \
  --config "$ULG_CONFIG" \
  --recipe javascript_test
```

Each result should have `"ok":true`, `"exit_code":0`, and non-empty recipe,
image, and sandbox-profile digests.

## 8. Durable review and cleanup

By default, durable audit files are stored under:

`$XDG_STATE_HOME/ulg/audit` when `XDG_STATE_HOME` is set, otherwise
`~/.local/state/ulg/audit`.

Use the controller-owned views instead of opening internal state directly:

```console
ulg diff TASK_ID
ulg audit TASK_ID
ulg clean TASK_ID --older-than-days 30 --yes
```

Sandbox execution should record `task_started`, `sandbox_finished`,
`task_completed`, and `workspace_discarded`. The sandbox event contains
normalized digests and outcome metadata, not raw command output or environment
values.

The corresponding `workspaces` state directory should contain no retained task
generation after completion.

For a deliberately retained test task, cleanup requires explicit acknowledgement:

```console
ulg clean TASK_ID --include-retained --yes
```

## 9. Phase 4 approval boundary

Ollama may request only recipe names allowlisted by trusted configuration. Every
model-requested patch or recipe execution that evaluates to `ask` requires an
exact action grant or a bounded recipe grant from the terminal approval service.
Expiry, changed configuration, replay, and mismatched scope fail closed.
