# CLI guide

This guide covers the implemented Phase 0–3 commands. Phase 4 model-triggered
approvals are not available yet.

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

## Current Phase 4 boundary

`sandbox-run` is an explicit operator command. Although the typed `run_task`
action and coding-tool bridge exist, Ollama is not offered that action until
Phase 4 implements exact recipe grants and trusted approval presentation.
