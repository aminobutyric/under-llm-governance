# MVP implementation status

This file tracks implementation evidence against the normative requirements in
the [development plan](development-plan.md) and [security model](security-model.md).
A checked implementation phase means its current automated tests pass; it does
not imply that later MVP phases or the complete adversarial acceptance suite are
finished.

## Phase 0: executable contracts

Status: implemented.

- The `uv` project, lockfile, CLI entry point, strict Pydantic schemas, policy,
  audit event types, provider interface, fake model, and package boundaries are
  present.
- Configuration rejects unknown fields and locks the Ollama endpoint to numeric
  loopback HTTP.
- Ruff, mypy, pytest, and CI checks are configured.

## Phase 1: read-only coding assistant

Status: implemented and locally exercised; further red-team coverage remains
part of the final MVP audit.

- `SnapshotWorkspaceManager` creates an application-owned disposable copy using
  descriptor-relative, no-follow source access.
- The copy rejects non-excluded symlinks, special files, mount changes, identity
  changes, and byte-quota overruns.
- Mandatory secret patterns, configured exclusions, `.git`, root and nested
  `.gitignore` rules are applied before repository files enter the snapshot.
- `list_files`, `read_file`, and literal `search_text` return typed bounded
  results and re-enforce mandatory exclusions.
- `OllamaModel` disables environment proxies and redirects, connects only to the
  validated loopback endpoint, uses bounded streaming JSON, and strictly
  validates every returned action.
- The controller enforces turn, tool-call, repeated-action, model-failure,
  context-byte, request-time, and task-time limits.
- `ulg inspect` persists allowlisted JSONL audit events outside the model
  workspace and destroys the snapshot on completion, failure, or cancellation.

On 2026-08-02, the complete read-only workflow was exercised against the local
`qwen3:14b` Ollama model. It completed two tool calls, rejected and retried one
malformed model action, recorded the complete event sequence, and left the
original repository unchanged with no retained task workspace.

## Phase 2: disposable editing

Status: implemented and locally exercised; further red-team coverage remains
part of the final MVP audit.

- Strict unified-diff actions support bounded create, update, and delete
  operations while rejecting traversal, renames, binary changes, stale hunks,
  duplicate paths, and unsupported headers.
- Multi-file patches are dry-run against an unreferenced staging copy, verified,
  and atomically published as a complete generation. A failed hunk removes the
  staging tree and leaves the current generation unchanged.
- Generation zero is verified against a source-derived, write-once manifest.
  Every successor is verified against its parent manifest and records the
  parent tree digest, bounded file metadata, byte total, and tree digest outside
  the model-visible workspace.
- Workspace bytes, file count, generation count, and manifest size are finite.
  Unsupported retention is rejected, and application state may not be created
  inside the selected original project.
- Copy verification, diff generation, and audit metadata use the immutable
  manifest chain. Diff generation reads only changed bounded UTF-8 files and
  rejects tampered generations, changed binary files, and oversized files.
- `ulg run` can produce and audit a new, no-follow patch artifact while leaving
  the original selected project unchanged. Export inside the original project
  or application task state is rejected by descriptor/inode ancestry checks.
- On cancellation or model failure after a complete generation, the CLI makes
  one bounded recovery export attempt and then explicitly audits and destroys
  task state. Incomplete successors are removed before retry and are never made
  current.
- Automated tests cover multi-file editing, failure atomicity, excluded paths,
  manifest tampering and quotas, bounded binary handling, exact export,
  protected-root isolation, recovery export, and cleanup.

On 2026-08-02, `ulg run` completed an editing workflow against the local
`qwen3:14b` Ollama model. It read the target, denied one malformed diff,
published a corrected generation with an audited parent/tree hash chain,
reviewed and exported the exact patch, left the original file unchanged, and
destroyed every task generation after export. The exported patch SHA-256 matched
the audit record.

The Phase 2 completion gate then passed the current lockfile check, Ruff format
and lint, strict mypy, and all 50 automated tests.

## Phase 3: offline verification

Status: complete.

- `run_task` proposals contain only a normalized trusted recipe name. Command
  arguments, images, mounts, environment, and sandbox flags are absent.
- Configuration requires `run_task` to remain `ask`, rejects invalid or
  duplicate recipe names, and requires the recipe allowlist to exactly match
  trusted recipe definitions.
- Policy asks for an allowlisted recipe, denies an unknown recipe, and fails
  closed when run policy is unavailable.
- The typed result contract records bounded output and normalized execution,
  recipe, image, sandbox-profile, timeout, cancellation, and duration metadata.
- Coding tools can execute only the selected trusted recipe through the sandbox
  runner. The Ollama adapter does not advertise `run_task` until Phase 4 can
  satisfy its mandatory scoped-approval decision.
- `ulg sandbox-preflight` addresses only the current user's standard rootless
  Unix socket and fails closed unless the socket is user-owned, Docker reports
  rootless mode, and cgroup v2 uses the systemd driver.
- The trusted runner is configured as an exact digest-qualified GHCR reference;
  execution uses that same reference with `--pull never` and verifies it appears
  in Docker's repository digests. The image has a digest-pinned Python base,
  runs as UID/GID 65532, and includes Python/pytest/Ruff, Go, and Node. Exact
  Debian and Python inventories are embedded in the image.
- `ulg sandbox-run` copies a verified disposable generation through a read-only
  bind mount into a bounded writable tmpfs. It uses no network, drops every
  capability, enables no-new-privileges and the built-in seccomp profile, uses
  a read-only container root, and applies CPU, memory, PID, swap, output,
  temporary-storage, and wall-clock limits.
- Commands are trusted argument arrays. Image, mount, environment, resource,
  namespace, and security options cannot appear in a model action.
- Timeout, cancellation, and output overflow kill the named container plus the
  complete local Docker client process group; cleanup force-removes any
  remaining container.
- Sandbox audit events record normalized recipe, image, profile digests,
  outcome, duration, output byte count, truncation, timeout, and cancellation,
  but never command output or environment values.

On 2026-08-05, all Python checks and 80 non-Docker automated tests passed. Four
live rootless-Docker acceptance groups then passed: representative Python, Go,
and JavaScript checks; network/socket/capability/privilege containment; timeout,
output-flood, and workspace disk limits; and PID, memory, environment-secret,
read-only-input, and original-integrity containment. The public CLI smoke tests
also passed for all three languages, and no sandbox container remained.

The first Phase 4 increment now supplies the exact grants and approval
presentation required for model-requested recipe execution in the coding loop.

## Phase 4: approvals and complete workflow

Status: implemented and security-accepted; beta publication remains pending.

The scoped-grant contract and first interactive approval workflow are
implemented:

- Exact-action grants bind the complete canonical action digest, action ID,
  task, complete trusted-configuration digest, one use, and a UTC expiry.
- Recipe grants bind the recipe name, trusted argv and sandbox-profile digest,
  task, complete trusted-configuration digest, configured maximum uses, and a
  UTC expiry.
- Grants can be issued only from the matching `ask` policy decision. Consumption
  is serialized and rejects unknown, expired, exhausted, wrong-task,
  wrong-scope, changed-configuration, mismatched-action, and replayed-action
  presentations without consuming a valid use on failure.
- Automated tests cover strict grant validation, deterministic security-relevant
  digests, expiry, forged identifiers, action mutation, task/configuration
  mismatch, replay, and concurrent maximum-use enforcement.
- Controller-generated patch prompts show only parsed file operations and size;
  they never render model rationale or raw patch content.
- Recipe prompts show the trusted recipe argv, pinned image, offline sandbox
  profile, expiry, and use bound. Users can deny, approve one exact action, or
  approve the exact recipe for its configured bounded uses.
- `ulg run` advertises only configured recipe names to Ollama, consumes a valid
  grant before execution, reuses bounded recipe grants without reprompting, and
  records approval, grant, tool, and sandbox lifecycle events.
- The final task report now includes approved-action and verified sandbox-run
  counts in addition to changed files and the model-authored summary.
- Automated integration tests cover approval, denial, bounded reuse, prompt
  injection resistance, original-project integrity, and CLI sandbox execution.
- Durable task records use strict, bounded, mode-`0600` JSON with atomic replace,
  directory synchronization, monotonic revisions, and a non-blocking process
  lease. Explicit plan, execute, review, retry, cancel, export, and discard states
  reject invalid transitions.
- Grant issuance and consumption commit complete use/action-ID state before the
  in-memory mutation becomes executable. Valid recipe grants can survive a
  restart, while configuration changes still revoke them.
- Effect scheduling is persisted before patch or sandbox execution. Resume walks
  and verifies the consecutive manifest chain, recovers a fully published patch,
  records an interrupted sandbox outcome as unknown, and revokes its recipe grant
  rather than silently repeating it.
- `ulg resume TASK_ID` continues a retained task from its verified generation;
  `ulg discard TASK_ID` destroys its workspace and stored grants. Failures retain
  state by default, while `--failure-mode recover` preserves bounded recovery
  export followed by discard.
- Restart tests cover atomic revisions, malformed state, exclusive leases,
  published-generation recovery, durable grant replay rejection, unknown sandbox
  outcomes, stale configuration, CLI resume, and explicit discard.

The current gate passes the lockfile check, Ruff formatting and lint, strict
mypy, and all 125 non-Docker automated tests. All five rootless-Docker
acceptance groups pass against the recorded digest-qualified candidate.

The review and operations increment adds bounded verified `ulg diff`, strict
redacted `ulg audit`, exact-target `ulg clean` with age/size preview and retained
work protection, actionable task commands, and an audit-derived completion
summary. The v0.1.0b1 foundation also centralizes version metadata, packages the
trusted policy template, adds private `ulg init`, discovers policy by explicit
argument/environment/XDG precedence, and requires an immutable GHCR runner
reference. The accepted manifest is published and anonymously pull-tested from
GHCR.

## MVP completion rule

The Phase 0–4 MVP implementation and its adversarial acceptance matrix are
complete. This is not yet a published beta: the runner still requires a
committed-tree rebuild, followed by the Milestone 4 release gates. Phase 5
network/dependency access remains post-MVP.
