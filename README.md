# Under LLM Governance

A security-first, local coding-agent project. The agent will use a local model
through Ollama, work within a user-selected project, and operate under
enforceable least-privilege controls.

This repository is currently in the architecture and planning stage. The first
implementation target is Linux, Go, Docker in rootless mode, and a locally
bound Ollama server. Ollama is an adapter, not a hard dependency of the core
design.

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
- Paths are resolved beneath the workspace root; string-prefix checks are not
  considered sufficient.
- Command execution is non-root, resource-limited, time-limited, and offline by
  default.
- Model output, repository content, tool output, and dependency output are all
  treated as untrusted input.
- Destructive, networked, credentialed, or externally visible actions require
  explicit policy and human approval.
- Every proposed and executed action produces an audit record with secrets
  redacted.

## Planned repository layout

```text
cmd/                         Go command entry points
  ulg/                       Local CLI
internal/
  controller/                Agent loop and request lifecycle
  model/                     Model-neutral contracts
    ollama/                  Ollama API adapter
  action/                    Typed action and result schemas
  policy/                    Deterministic authorization decisions
  approval/                  Human approval workflow
  tools/                     Read, search, patch, diff, and task tools
  workspace/                 Task copies, snapshots, and promotion
  sandbox/                   Isolated process runner
  audit/                     Structured, redacted event log
  config/                    Configuration loading and validation
config/                      Example policy files
docs/                        Architecture, security model, and plans
testdata/adversarial/        Prompt-injection and sandbox escape fixtures
```

Implementation directories will be introduced phase by phase instead of being
filled with empty placeholders.

## Documentation

- [Architecture](docs/architecture.md)
- [Security model](docs/security-model.md)
- [Development plan](docs/development-plan.md)
- [Trust-boundary decision](docs/decisions/0001-trusted-controller.md)
- [Example policy](config/policy.example.yaml)

## Initial scope

The MVP supports one local user and one task at a time. It can inspect a copied
workspace, propose patches, display the resulting diff, and run preconfigured
checks without network access. It will not install dependencies, push code,
deploy software, manage secrets, or make arbitrary host changes.

## Definition of success

A successful MVP can complete a small coding task while an adversarial file in
the repository cannot make it read outside the workspace, contact the network,
consume unbounded host resources, or bypass an approval decision.
