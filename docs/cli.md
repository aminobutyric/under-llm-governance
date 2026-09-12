# CLI guide

This guide covers the implemented Phase 0–4 commands, including scoped terminal
approvals, durable resume, bounded review, redacted audit summaries, and explicit
cleanup.

## Setup diagnostics (upcoming release)

From this checkout, run `uv run ulg doctor`, optionally with `--config PATH` or
`--json`. This command is not included in the published `0.1.0b3` package.
It checks Linux amd64, supported Python, trusted configuration, the local Ollama
API and installed model, rootless Docker/cgroups, and the local runner digest.
It does not load a model, run a container, pull an image, or change configuration.
Fix suggestions are displayed for the operator to run explicitly.

Exit code 0 means every setup check passed; 2 means at least one check failed or
could not run. JSON contains `ready` and `checks`, each with `name`, `status`
(`pass`, `fail`, or `skip`), `message`, and `fix`. The API request disables
environment proxies and redirects and bounds timeouts and response size.
A passed model check confirms installation, not inference speed or task quality.

## Path rules

`ulg` treats command-line paths explicitly:

- `--workspace` selects the source directory to snapshot. A relative value is
  resolved from the shell's current directory, not from the ULG repository.
- `--config` selects trusted policy. A relative value is also resolved from the
  current directory.
- `--state-dir`, when supplied, must be outside the selected workspace.
- `--output` must name a new path outside the selected workspace and ULG task
  state.

Policy discovery is deterministic: explicit `--config`, then `ULG_CONFIG`, then
`$XDG_CONFIG_HOME/ulg/policy.toml` (or `~/.config/ulg/policy.toml`). It never
trusts a policy merely because it exists in the target project.

## Initialize the user policy

Create the default private policy and select the reference Ollama model:

```console
ulg init
ollama pull qwen3-coder:30b
```

The new file is mode `0600`; its parent directory is private when newly created.
Initialization refuses to overwrite anything by default and rejects symlink or
non-regular destinations even with `--force`. To make an intentional atomic
update or use another model:

```console
ulg init --force --model qwen3:8b
ulg init --output /trusted/path/policy.toml
```

## Prepare shell paths

Set these once in each terminal, replacing the first value if your checkout
moves:

```console
export ULG_REPO=/path/to/warrant
```

`ULG_REPO` is a shell convenience used by the development examples. A custom
policy can still be selected with `ULG_CONFIG` or `--config`.

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
  --task "Explain this project and cite the files you read" \
  --model qwen3-coder:30b
```

The initialized XDG policy is used automatically.

An absolute workspace works from any current directory too:

```console
uv run --project "$ULG_REPO" --frozen ulg inspect \
  --workspace /absolute/path/to/small-project \
  --task "Explain this project and cite the files you read" \
  --model qwen3-coder:30b
```

## Optional editable command installation

Developers who want `ulg` directly on `PATH` can install the checkout as an
editable uv tool:

```console
uv tool install --editable "$ULG_REPO"
ulg --help
```

The trusted policy is deliberately not inferred from an arbitrary target
project. With `ulg init` complete, no configuration argument is needed:

```console
cd /path/to/small-project
ulg inspect \
  --workspace . \
  --task "Explain this project and cite the files you read" \
  --model qwen3-coder:30b
```

Re-run the editable install only if the environment is removed; source changes
are visible without reinstalling.

## Implemented commands

| Command | Purpose | Needs Ollama | Needs rootless Docker |
|---|---|---:|---:|
| `ulg init` | Create a private trusted user policy | No | No |
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
