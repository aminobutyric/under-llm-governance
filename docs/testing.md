# Testing through Phase 3

This guide verifies every implemented user path through Phase 3. Run commands
from the repository root unless a section explicitly says they work anywhere.

## 1. Prerequisites

- Linux with Python 3.11 or newer and `uv`.
- Rootless Docker for Phase 3 tests.
- A running local Ollama server and an installed model for Phase 1–2 manual
  tests.

Prepare reusable paths:

```console
export ULG_REPO=/home/amin-mth/Projects/Personal/under-llm-governance
export ULG_CONFIG="$ULG_REPO/config/policy.example.toml"
cd "$ULG_REPO"
uv sync --frozen
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
```

The normal pytest run skips live Docker tests unless explicitly enabled.

## 3. Live rootless-Docker acceptance gate

Verify the daemon first:

```console
uv run --frozen ulg sandbox-preflight
```

Expected fields include `"rootless":true`, `"cgroup_version":"2"`, and
`"cgroup_driver":"systemd"`.

If the runner image has not been built on this machine:

```console
docker build --pull=false --tag ulg-runner:phase3 "$ULG_REPO/runner"
docker image inspect ulg-runner:phase3 --format '{{.Id}}'
```

The reported image ID must exactly equal `sandbox.image_digest` in the trusted
policy. A rebuild may produce a new ID; reviewing and changing that digest is a
trusted-operator action.

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

## 8. Audit and cleanup inspection

By default, durable audit files are stored under:

`$XDG_STATE_HOME/ulg/audit` when `XDG_STATE_HOME` is set, otherwise
`~/.local/state/ulg/audit`.

List recent files and inspect one:

```console
ls -lt "${XDG_STATE_HOME:-$HOME/.local/state}/ulg/audit" | head
less "${XDG_STATE_HOME:-$HOME/.local/state}/ulg/audit/<audit-file>.jsonl"
```

Sandbox execution should record `task_started`, `sandbox_finished`,
`task_completed`, and `workspace_discarded`. The sandbox event contains
normalized digests and outcome metadata, not raw command output or environment
values.

The corresponding `workspaces` state directory should contain no retained task
generation after completion.

## 9. Phase boundary

Do not expect an Ollama-driven coding task to execute `run_task` yet. The direct
operator command and isolated runner are complete; exact approval grants and
model-facing recipe execution belong to Phase 4.
