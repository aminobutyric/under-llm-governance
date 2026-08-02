# Under LLM Governance

A security-first, local coding-agent project. The agent will use a local model
through Ollama, work within a user-selected project, and operate under
enforceable least-privilege controls.

This repository has executable read-only inspection and disposable editing
workflows and is working toward the sandbox and approval phases of its MVP. The
locked baseline is Linux, Python 3.11+, `uv`, rootless Docker, and a locally
bound Ollama server. Ollama is an adapter, not a hard dependency of the core
design.

The repository is licensed under `MPL-2.0`.

## Core idea

The model never receives ambient access to the host. It proposes typed actions
such as reading a relative path, applying a patch, or running a configured test.
A trusted controller validates every proposal, applies policy, requests human
approval when necessary, and executes accepted actions in an isolated task
workspace.

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
- Commands require a narrow approval grant for an exact configured recipe;
  networked, credentialed, or externally visible actions are absent from the
  MVP.
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
.github/workflows/ci.yml     Locked lint, type-check, and test workflow
config/                      Example trusted policy files
docs/                        Architecture, security model, plans, and ADRs
testdata/adversarial/        Inert injection, path, and resource fixtures
```

The Phase 0 package contains the controller dry-run path, strict action and
configuration schemas, deterministic policy, audit-safe events, a fake model,
and explicit contracts for approvals, tools, workspaces, and sandboxes. Concrete
effectful implementations are introduced only in the development phase that
secures and tests them.

## Quick start

```console
uv sync
uv run ulg dry-run
uv run pytest
```

The dry run crosses model, schema, policy, controller, and audit boundaries but
does not read a workspace or execute a tool.

To use an already-installed local Ollama model against a disposable read-only
snapshot:

```console
uv run ulg inspect \
  --workspace /path/to/project \
  --task "Explain this project and cite the files you read" \
  --model qwen3:14b
```

The original project is never the model's working directory. Task snapshots are
destroyed after inspection, while allowlisted audit events remain under the
application state directory.

To ask the model to produce a reviewable patch without modifying the original
project:

```console
uv run ulg run \
  --workspace /path/to/project \
  --task "Make the requested change" \
  --output /path/to/new-change.patch \
  --model qwen3:14b
```

The output path must not already exist. The exported unified diff is the only
artifact written outside application state; applying it to the original project
is deliberately left to the user.

## Documentation

- [Architecture](docs/architecture.md)
- [Security model](docs/security-model.md)
- [Development plan](docs/development-plan.md)
- [MVP implementation status](docs/mvp-status.md)
- [Trust-boundary decision](docs/decisions/0001-trusted-controller.md)
- [Python implementation baseline](docs/decisions/0002-python-baseline.md)
- [Security mechanisms](docs/decisions/0003-security-mechanisms.md)
- [License decision](docs/decisions/0004-license-mpl.md)
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
