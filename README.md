# Warrant

A security-first, local coding-agent project. The agent will use a local model
through Ollama, work within a user-selected project, and operate under
enforceable least-privilege controls.

This repository has executable read-only inspection, disposable editing,
offline sandbox verification, and scoped terminal approval workflows. The
locked baseline is Linux, Python 3.11+, `uv`, rootless Docker, and a locally
bound Ollama server. Ollama is an adapter, not a hard dependency of the core
design.

The repository is licensed under `MPL-2.0`.

## Core idea

The model never receives ambient access to the host. It proposes typed actions
such as reading a relative path, applying a patch, or running a configured test.
A trusted controller validates every proposal and applies deterministic policy.
Implemented `allow` decisions execute inside disposable boundaries; `ask`
decisions require trusted approval presentation and exact, bounded grants.

Security instructions in a system prompt are useful guidance, but they are not
a permission boundary.

## Security invariants

- The model cannot directly access files, processes, credentials, or networks.
- A task can access only its disposable workspace by default.
- Secret-like and policy-excluded files are removed before any workspace bytes
  can enter model context or audit data.
- Paths are resolved beneath the workspace root; string-prefix checks are not
  considered sufficient, and symlinks are rejected rather than followed.
- Multi-file patches become visible only after every hunk validates and the new
  workspace generation is complete.
- Command execution is non-root, resource-limited, time-limited, and offline by
  default.
- Model output, repository content, tool output, and dependency output are all
  treated as untrusted input.
- Model-requested commands are policy-gated and require a narrow approval grant
  for an exact configured recipe. The `sandbox-run` command remains an explicit
  operator action.
- Every proposed and executed action produces an audit record with secrets
  redacted before serialization or persistence.

## Repository layout

```text
pyproject.toml               Package metadata, CLI entry point, tool settings
uv.lock                      Reproducible dependency lock
src/ulg/
  cli.py                     Local CLI
  controller.py              Bounded agent loop and request lifecycle
  actions/                   Typed, versioned action and result schemas
  model/                     Provider contract, fake, and Ollama adapters
  policy/                    Deterministic authorization decisions
  approval/                  Scoped capability grants
  tools/                     Read, search, patch, diff, and recipe tools
  workspace/                 Copies, generations, exclusions, patch export
  sandbox/                   Isolated process runner
  audit/                     Structured pre-write redaction and JSONL sink
  config/                    Strict TOML configuration loading
tests/                       Unit, integration, and security suites
runner/                      Digest-pinned multi-language sandbox image
.github/workflows/           Locked CI and tag-driven release workflows
config/                      Example trusted policy files
docs/                        Architecture, security model, plans, and ADRs
testdata/adversarial/        Inert injection, path, and resource fixtures
testdata/phase3/             Python, Go, and JavaScript smoke projects
```

The current implementation includes strict contracts, deterministic policy,
bounded Ollama access, disposable workspace generations, reviewed patch export,
the fixed offline sandbox, normalized audit events, and manual acceptance paths.
See [MVP implementation status](docs/mvp-status.md) for evidence and the exact
Phase 4 boundary.

## Quick start

Start with the [first-task tutorial](docs/first-task.md) for a small, reviewable
Python change. The upcoming release adds `ulg doctor`; from this checkout use
`uv run ulg doctor` to check setup and see suggested fixes.

The public beta will install as a normal command-line tool:

```console
uv tool install warrant-llm==0.1.0b3
ulg init
ollama pull qwen3-coder:30b
ulg dry-run
ulg sandbox-preflight
```

`ulg init` creates a private policy at
`$XDG_CONFIG_HOME/ulg/policy.toml` or `~/.config/ulg/policy.toml`. Use
`ulg init --model MODEL` to select another installed Ollama model. Contributors
can run the same workflow from a checkout:

```console
uv sync --frozen
uv run --frozen ulg init
uv run --frozen ulg dry-run
uv run --frozen ulg sandbox-preflight
uv run --frozen pytest
```

These development commands assume the repository root is the current directory.
For a command that works from any directory, make the ULG checkout explicit:

```console
export ULG_REPO=/path/to/warrant

uv run --project "$ULG_REPO" --frozen ulg inspect \
  --workspace /absolute/path/to/small-project \
  --task "Explain this project and cite the files you read" \
  --model qwen3-coder:30b
```

See the [CLI guide](docs/cli.md) for path rules, optional editable installation,
all commands, and exit codes.

## Offline sandbox setup

Phase 3 requires rootless Docker with cgroup v2 and the systemd cgroup driver.
The release policy names the trusted GHCR runner by its immutable registry
digest. Pull that exact reference and run preflight:

```console
docker pull "$(python -c 'import tomllib,pathlib; print(tomllib.loads((pathlib.Path.home()/".config/ulg/policy.toml").read_text())["sandbox"]["image"])')"
uv run --frozen ulg sandbox-preflight
```

The checked-in template contains the exact tested candidate digest. That
manifest is public in GHCR and has passed an anonymous digest-qualified pull.
Replacing the configured reference remains an explicit trusted-operator action.

Run the checked-in offline smoke projects without exposing their original
directories to a writable mount:

```console
uv run --frozen ulg sandbox-run \
  --workspace testdata/phase3/python \
  --config config/policy.example.toml \
  --recipe test
uv run --frozen ulg sandbox-run \
  --workspace testdata/phase3/go \
  --config config/policy.example.toml \
  --recipe go_test
uv run --frozen ulg sandbox-run \
  --workspace testdata/phase3/javascript \
  --config config/policy.example.toml \
  --recipe javascript_test
```

`sandbox-run` is the direct operator acceptance path. During `ulg run`, the
model may also request an allowlisted recipe. The controller displays its
trusted command and sandbox limits and lets the user deny it, approve that exact
action once, or issue a time- and use-bounded grant for that recipe.

The dry run crosses model, schema, policy, controller, and audit boundaries but
does not read a workspace or execute a tool.

To use an already-installed local Ollama model against a disposable read-only
snapshot:

```console
uv run --frozen ulg inspect \
  --workspace /path/to/project \
  --config config/policy.example.toml \
  --task "Explain this project and cite the files you read" \
  --model qwen3:14b
```

The original project is never the model's working directory. Task snapshots are
destroyed after inspection, while allowlisted audit events remain under the
application state directory.

To ask the model to produce a reviewable patch without modifying the original
project:

```console
uv run --frozen ulg run \
  --workspace /path/to/project \
  --config config/policy.example.toml \
  --task "Make the requested change" \
  --output /path/to/new-change.patch \
  --model qwen3:14b
```

The output path must not already exist. The exported unified diff is the only
artifact written outside application state; applying it to the original project
is deliberately left to the user.

Coding tasks have durable lifecycle state. A failure or cancellation keeps the
last manifest-verified generation by default and prints its task identifier:

```console
uv run ulg resume TASK_ID
uv run ulg diff TASK_ID
uv run ulg audit TASK_ID
uv run ulg discard TASK_ID
```

`resume` reopens the verified generation and refuses changed trusted
configuration. It does not replay an interrupted effect: a fully published patch
is recovered from its manifest, while an interrupted sandbox result is marked
unknown and its recipe grant is revoked before the model continues. Use
`--failure-mode recover` with `ulg run` to retain the former behavior of exporting
the last complete patch and discarding the task after a controlled failure.

Durable task files are mode `0600` beneath the application state directory and
contain the original task text, trusted paths and configuration digest, current
generation, lifecycle phase, and bounded effect journal. Successful export and
explicit discard destroy workspace generations and revoke stored grants; the
small lifecycle record remains for later audit and cleanup commands.

`ulg diff` verifies the retained generation and returns a byte-bounded review;
`ulg audit` strictly parses the allowlisted event log into redacted counts and a
bounded lifecycle timeline. Cleanup always requires exact task IDs, reports task
age and stored bytes, and asks for confirmation. Resumable work is protected
unless `--include-retained` is explicit:

```console
uv run ulg clean TASK_ID --older-than-days 30 --yes
uv run ulg clean TASK_ID --include-retained --yes
```

Approval prompts are written to the terminal separately from the final JSON
report. Patch prompts contain parsed file operations rather than raw model prose
or patch content. Recipe prompts contain only trusted configuration, including
the fixed command, pinned image, offline sandbox limits, expiry, and use count.
Invalid input and unavailable approval handling fail closed.

## Documentation

- [First-task tutorial](docs/first-task.md)
- [Beta adoption checklist](docs/beta-adoption.md)

- [Architecture](docs/architecture.md)
- [Security model](docs/security-model.md)
- [v0.1 security acceptance matrix](docs/security-acceptance-matrix.md)
- [v0.1.0b1 runner acceptance evidence](docs/release-evidence/v0.1.0b1-runner.md)
- [Development plan](docs/development-plan.md)
- [MVP implementation status](docs/mvp-status.md)
- [MVP readiness checklist](docs/mvp-checklist.md)
- [v0.1 beta release checklist](docs/beta-release-checklist.md)
- [Beta operations guide](docs/operations.md)
- [Release procedure](docs/releasing.md)
- [Beta support](SUPPORT.md)
- [Security reporting](SECURITY.md)
- [CLI guide](docs/cli.md)
- [Testing through Phase 4](docs/testing.md)
- [Trust-boundary decision](docs/decisions/0001-trusted-controller.md)
- [Python implementation baseline](docs/decisions/0002-python-baseline.md)
- [Security mechanisms](docs/decisions/0003-security-mechanisms.md)
- [License decision](docs/decisions/0004-license-mpl.md)
- [Durable task-state decision](docs/decisions/0005-durable-task-state.md)
- [Open-core strategy](docs/open-core-strategy.md)
- [Example policy](config/policy.example.toml)

## Initial scope

The MVP supports one local user and one task at a time. It can inspect a copied
workspace, propose patches, display the resulting diff, and run preconfigured
checks without network access. It emits a patch for the human to apply outside
the agent's write path. It will not install dependencies, push code, deploy
software, manage secrets, or make arbitrary host changes.

## Definition of success

A successful MVP can complete a small coding task while an adversarial file in
the repository cannot make it read outside the workspace, contact the network,
consume unbounded host resources, or bypass an approval decision.
