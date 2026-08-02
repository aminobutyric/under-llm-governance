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

Status: not implemented.

Required next: a pinned runner image, fixed trusted recipes, rootless Docker
with no network/capabilities/privilege escalation, mandatory resource limits,
bounded output, cancellation, and adversarial process tests.

## Phase 4: approvals and complete workflow

Status: not implemented.

Required next: exact recipe grants with digest/task/use/expiry binding, normalized
approval prompts, task persistence and resume behavior, review/export/discard
commands, and a final report that separates model claims from verified results.

## MVP completion rule

The project is not an MVP release until Phases 0–4 are implemented and every
applicable adversarial acceptance test in `docs/security-model.md` proves both
containment and useful audit evidence. Phase 5 network/dependency access remains
post-MVP.
