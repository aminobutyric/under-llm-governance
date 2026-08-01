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
| `apply_patch` | Modify the task copy | Allow and audit |
| `show_diff` | Inspect pending changes | Allow |
| `run_task` | Run a configured test/lint/format recipe | Allow and audit |

Arbitrary shell execution, network access, dependency installation, Git push,
and deployment are deliberately absent from the MVP schema.

### Policy engine

Makes deterministic decisions without consulting an LLM:

- `allow`: execute immediately;
- `ask`: require an exact, time-bounded user approval;
- `deny`: refuse and explain the violated rule.

The policy receives normalized action data and task context. It does not accept
free-form shell strings as policy expressions. Deny wins over ask, and ask wins
over allow.

### Tools

Tools implement narrow operations and validate their own inputs even after a
policy decision. Output is bounded by bytes, lines, matches, and duration before
it is returned to either the model or user.

File operations use workspace-relative paths. On Linux, the implementation
should use file-descriptor-relative operations and secure resolution beneath an
already-open workspace root. Symlinks and special files are denied by default.

### Workspace manager

Creates a per-task disposable copy beneath application-owned state. The original
directory is initially read-only input. Changes are reviewed as a diff and are
promoted to the original only through a separate, explicit operation.

Promotion must detect that the original changed after the task began. On a
conflict, it stops rather than overwriting newer user work.

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

The image and all runtime security flags come from trusted configuration, never
from a model action.

### Approval service

Displays the exact normalized action, affected paths, command recipe, network
destination if any, and expected impact. Approval applies to one action and
expires. A vague approval such as “allow future commands” is out of scope for
the MVP.

### Audit log

Records task lifecycle events, proposed actions, decisions, approvals, execution
metadata, exit status, resource-limit termination, and promotion. Logs contain
hashes or bounded previews rather than complete sensitive file contents. Secret
redaction happens before persistence.

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
  -> optionally promote after user approval
```

## Configuration layers

Configuration is merged from most restrictive to least specific:

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
- Whether workspace promotion uses patches, a local clone, or filesystem
  snapshots.
- How approved network access will be allowlisted and observed.
- Whether stronger isolation such as a microVM is needed for multi-user use.
