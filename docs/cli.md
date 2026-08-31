# CLI guide

This guide covers the implemented Phase 0–4 commands, including scoped terminal
approvals, durable resume, bounded review, redacted audit summaries, and explicit
cleanup.

## Path rules

`ulg` treats command-line paths explicitly:

- `--workspace` selects the source directory to snapshot. A relative value is
  resolved from the shell's current directory, not from the ULG repository.
- `--config` selects trusted policy. A relative value is also resolved from the
  current directory.
- `--state-dir`, when supplied, must be outside the selected workspace.
- `--output` must name a new path outside the selected workspace and ULG task
  state.

The default policy path is `config/policy.example.toml` relative to the current
directory. For commands launched elsewhere, pass an absolute `--config` path or
set `ULG_CONFIG` to one.

## Prepare shell paths

Set these once in each terminal, replacing the first value if your checkout
moves:

```console
export ULG_REPO=/home/amin-mth/Projects/Personal/under-llm-governance
export ULG_CONFIG="$ULG_REPO/config/policy.example.toml"
```

`ULG_REPO` is a shell convenience used by the examples. `ULG_CONFIG` is read by
the CLI and becomes the default for `--config`.

## Run from the repository

From the repository root, `uv` discovers `pyproject.toml` automatically:

```console
cd "$ULG_REPO"
uv sync --frozen
uv run --frozen ulg --help
uv run --frozen ulg dry-run
```

## Run from any directory

Use `uv --project` to locate ULG while leaving the shell's current directory
unchanged. In this example, `--workspace .` means `/path/to/small-project`:

```console
cd /path/to/small-project
uv run --project "$ULG_REPO" --frozen ulg inspect \
  --workspace . \
  --config "$ULG_CONFIG" \
  --task "Explain this project and cite the files you read" \
  --model qwen3:14b
```

Because `ULG_CONFIG` was exported above, the explicit `--config` option may be
omitted. Keeping it in copied commands makes the trust source visible.

An absolute workspace works from any current directory too:

```console
uv run --project "$ULG_REPO" --frozen ulg inspect \
  --workspace /absolute/path/to/small-project \
  --config "$ULG_CONFIG" \
  --task "Explain this project and cite the files you read" \
  --model qwen3:14b
```

## Optional editable command installation

Developers who want `ulg` directly on `PATH` can install the checkout as an
editable uv tool:

```console
uv tool install --editable "$ULG_REPO"
ulg --help
```

The trusted policy is deliberately not inferred from an arbitrary target
project. Continue to export `ULG_CONFIG` or pass `--config`:

```console
cd /path/to/small-project
ulg inspect \
  --workspace . \
  --config "$ULG_CONFIG" \
  --task "Explain this project and cite the files you read" \
  --model qwen3:14b
```

Re-run the editable install only if the environment is removed; source changes
are visible without reinstalling.

## Implemented commands

| Command | Purpose | Needs Ollama | Needs rootless Docker |
|---|---|---:|---:|
| `ulg dry-run` | Exercise contracts without filesystem or process effects | No | No |
| `ulg inspect` | Inspect a disposable read-only snapshot | Yes | No |
| `ulg run` | Edit disposable generations and export a patch | Yes | No |
| `ulg resume` | Continue one retained durable task | Yes | Only for approved recipes |
| `ulg diff` | Review one retained task's bounded verified diff | No | No |
| `ulg audit` | Show one task's concise redacted lifecycle | No | No |
| `ulg discard` | Destroy one retained workspace and its grants | No | No |
| `ulg clean` | Delete exact task IDs after size/age preview | No | No |
| `ulg sandbox-preflight` | Validate the current user's Docker daemon | No | Yes |
| `ulg sandbox-run` | Run one trusted recipe in the offline sandbox | No | Yes |

Use command-specific help whenever copying an invocation:

```console
uv run --project "$ULG_REPO" --frozen ulg inspect --help
uv run --project "$ULG_REPO" --frozen ulg run --help
uv run --project "$ULG_REPO" --frozen ulg sandbox-run --help
```

## Exit codes

- `0`: command or selected recipe succeeded.
- `1`: the sandbox ran safely, but the selected recipe failed.
- `2`: configuration, validation, workspace, model, Docker, or infrastructure
  failure.
- `130`: cancellation by the user.

## Durable review and cleanup

`ulg run` prints the task ID as soon as durable state exists. If a task is
retained, use the printed commands to inspect and continue it:

```console
ulg diff TASK_ID
ulg audit TASK_ID
ulg resume TASK_ID
ulg discard TASK_ID
```

`diff` returns JSON containing the verified generation, total and returned byte
counts, a truncation flag, and the bounded unified diff. `audit` validates each
complete allowlisted event and returns counts plus at most 200 redacted timeline
entries; raw model, patch, tool-output, and environment payloads are absent.

Cleanup takes exact task identifiers and prints age and stored bytes before any
deletion. It confirms interactively unless `--yes` is supplied. Retained tasks
require the additional `--include-retained` acknowledgement. An optional age
gate skips newer selected tasks:

```console
ulg clean TASK_ID --older-than-days 30 --yes
ulg clean TASK_ID --include-retained --yes
```
