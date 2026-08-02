# Architecture

## Design goals

1. Enforce directory-scoped access outside the model.
2. Make every effect attributable to a typed, validated action.
3. Keep the trusted computing base small and testable.
4. Make unsafe capabilities opt-in, narrow, temporary, and visible.
5. Support other model providers and sandbox backends later without changing
   the policy model.

## System context

```text
                         trusted host process
                    +-----------------------------+
User task ---------->  CLI / controller            |
                    |       |                      |
                    |       +----> Ollama adapter -+----> Ollama on loopback
                    |       |                      |
                    |       v                      |
Approval UI <-------+-- policy engine              |
                    |       |                      |
Audit log <---------+-------+                      |
                    +-------|----------------------+
                            | accepted action only
                            v
                    +-----------------------------+
                    | disposable sandbox          |
                    | task workspace only         |
                    | no network by default       |
                    +-----------------------------+
```

The controller is trusted. Model responses, workspace contents, command output,
and sandboxed processes are untrusted. The controller may launch a sandbox, but
the model must never control container images, mount sources, security flags, or
the Docker socket.

## Main components

### Controller

Owns the task state machine and conversation history. It sends the model only
the context needed for the current step, validates structured responses, asks
the policy engine for a decision, invokes approved tools, and returns bounded
tool results to the model.

The controller must enforce maximum turns, wall-clock duration, token/context
budget, tool-call count, and repeated-failure limits.

### Model adapter

Defines a provider-neutral chat and tool-calling contract. The initial Ollama
adapter communicates only with a configured loopback endpoint. It does not
receive filesystem or sandbox handles.

### Action schema

The model proposes a closed set of versioned actions. Each action has a name,
typed arguments, a task identifier, and an explanation intended for the user.
Unknown fields and unknown action types are rejected.

Initial action set:

| Action | Purpose | Initial decision |
|---|---|---|
| `list_files` | Enumerate a bounded directory | Allow |
| `read_file` | Read a bounded regular file | Allow |
| `search_text` | Search text with result limits | Allow |
| `apply_patch` | Create a new task-workspace generation | Allow and audit |
| `show_diff` | Inspect pending changes | Allow |
| `run_task` | Select a fixed test/lint/format recipe by name | Scoped approval |

Arbitrary shell execution, network access, dependency installation, Git push,
and deployment are deliberately absent from the MVP schema.

### Policy engine

Makes deterministic decisions without consulting an LLM:

- `allow`: execute immediately;
- `ask`: require an exact action approval or a bounded capability grant;
- `deny`: refuse and explain the violated rule.

The policy receives normalized action data and task context. It does not accept
free-form shell strings as policy expressions. Deny wins over ask, and ask wins
over allow.

### Tools

Tools implement narrow operations and validate their own inputs even after a
policy decision. Output is bounded by bytes, lines, matches, and duration before
it is returned to either the model or user.

File operations use workspace-relative paths. On Linux, the implementation uses
file-descriptor-relative operations beneath an already-open workspace root and
opens path components without following symlinks. `Clean`, `resolve`, and
string-prefix comparisons are not authorization mechanisms. A future `openat2`
backend may strengthen and simplify this implementation, but it must preserve
the same package contract.

Every tool result has per-call byte, line, match, and duration limits plus a
task-wide context budget. Truncation is explicit in the structured result.

### Workspace manager

Creates a per-task disposable copy beneath application-owned state. The copy
walker never follows symlinks and refuses files that change identity while being
copied. It applies built-in secret exclusions, user exclusions, and `.gitignore`
exclusions before reading file bytes. The same exclusions are enforced again by
read and search tools.

The original directory is read-only input. Each successful patch produces a new
workspace generation. The controller exports a diff artifact; it has no MVP
operation that writes the diff back into the original directory. Workspaces and
containers are destroyed after export or discard. Retaining a workspace is an
explicit user action, not the default.

### Patch transaction

The controller serializes workspace mutations. `apply_patch` parses and
validates every path and hunk against the current generation, constructs the
complete result in an unreferenced staging generation, and checks its manifest.
Only then does task state point to the new generation. A validation, write, or
crash failure leaves the previous generation active and returns a structured
failure; incomplete generations are never exposed to the model as current.

This is atomic from the task state machine's perspective. It does not claim that
separate host files can be updated in one filesystem transaction.

### Sandbox runner

Executes only policy-selected recipes. The initial Docker profile should use:

- rootless Docker;
- a non-root UID and GID;
- `--network none`;
- `--cap-drop ALL`;
- `--security-opt no-new-privileges=true`;
- the default seccomp profile;
- a read-only container root;
- one writable task-workspace mount;
- bounded temporary storage;
- CPU, memory, PID, output, and wall-clock limits;
- no host devices, host namespaces, credentials, or Docker socket.

The MVP defaults are 512 MiB memory, 1 CPU, 128 PIDs, 60 seconds wall-clock,
128 MiB temporary storage, and 1 MiB combined stdout/stderr. These are finite,
strictly validated trusted configuration values; “unlimited” is not accepted.

The image and all runtime security flags come from trusted configuration, never
from a model action.

### Approval service

Displays normalized controller data, never model-authored approval prose. It can
approve one action or issue a bounded grant containing the exact recipe digest,
task identifier, maximum uses, and expiry. Any recipe or policy change
invalidates the grant. General per-task authority is not supported.

Read/search/diff and small patches in the disposable workspace are automatic and
logged. High-volume or destructive-looking patches may cross a policy threshold
and require approval. `run_task` requires a valid recipe grant.

### Audit log

Records task lifecycle events, proposed actions, decisions, grants, execution
metadata, exit status, resource-limit termination, patch export, and cleanup.
Callers construct audit-safe events from allowlisted fields; raw prompts, file
contents, command output, and environment data are not accepted by the sink.
Redaction and size limiting happen before serialization and persistence.
Append-only JSONL is the MVP format. Hash chaining is a documented fast-follow,
not an MVP integrity claim.

## Request lifecycle

```text
User task
  -> create isolated task workspace
  -> gather bounded initial context
  -> ask model for one or more typed actions
  -> parse and validate schema
  -> normalize paths and arguments
  -> evaluate deterministic policy
  -> deny, ask, or execute
  -> bound and redact result
  -> append audit event
  -> return result to model
  -> stop on completion or configured limit
  -> show final diff and verification results
  -> export a reviewable patch
  -> destroy the task workspace after export or discard
```

## Configuration layers

Strict TOML configuration is merged from most restrictive to least specific:

1. compiled security invariants that configuration cannot disable;
2. administrator or installation policy;
3. user policy;
4. project policy;
5. task-specific restrictions.

A lower layer may remove permissions but may not silently grant a capability
forbidden by a higher layer.

## Deferred decisions

- Whether Linux Landlock should be added beneath or instead of the container
  backend for file-only tools.
- How approved network access will be allowlisted and observed.
- Whether stronger isolation such as a microVM is needed for multi-user use.
- Whether an `openat2` native helper provides enough benefit over the initial
  descriptor-relative Python implementation.
