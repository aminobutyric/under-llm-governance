# ADR 0003: Lock the MVP containment mechanisms

- Status: accepted
- Date: 2026-08-02

## Context

The original architecture stated correct goals but left important mechanisms
underspecified: secret exclusion, path containment, patch failure, approval
scope, recipe execution, resource limits, redaction timing, and workspace
lifecycle.

## Decision

### Files and secrets

The workspace copier rejects symlinks and special files and does not follow
links. It applies built-in secret patterns, user patterns, `.git` exclusion, and
gitignore exclusions before reading file bytes. Read and search enforce the same
policy again. Directory-descriptor-relative, no-follow operations enforce the
workspace boundary; canonical-string prefix comparison does not.

This is exclusion, not secret detection. Unusually named secrets can evade a
glob list, so users must be able to preview the copy manifest and add exclusions
before starting a task.

### Patch atomicity

All hunks are parsed and dry-run against one immutable workspace generation. A
complete new generation is built outside the active reference. Task state moves
to it only after every write and manifest check succeeds. A failure keeps the
old generation active and yields structured error details.

### Approvals

Read, search, diff, and ordinary patches inside the disposable workspace are
automatic and logged. Policy may require approval for deletion or large-change
thresholds. A command grant names the exact trusted recipe digest, task, maximum
uses, and expiry. Broad task-level approval does not exist.

### Commands and resources

`run_task` accepts only a recipe name mapped by trusted policy to an immutable
argument array. Model data cannot alter commands, images, mounts, environment,
or sandbox flags. The MVP defaults are 512 MiB memory, 1 CPU, 128 PIDs, 60
seconds, 128 MiB temporary storage, and 1 MiB combined output. Configuration
must contain finite positive limits.

### Audit and cleanup

Callers convert data to bounded, allowlisted event fields and redact them before
serialization. The JSONL sink rejects raw payload types. Hash chaining is
deferred and the MVP makes no tamper-evidence claim. The controller exports a
diff but cannot modify the original project. Containers and workspaces are
destroyed after export or discard unless the user explicitly requests bounded
retention.

### Prompt injection

File-content injection remains in scope. Typed actions do not prevent model
manipulation; they reduce the authority available to a manipulated model. Every
valid action still requires validation and policy evaluation.

## Consequences

Workspace copies consume more disk because patch generations favor clear
transaction semantics over clever in-place recovery. Some legitimate secret-like
files will be absent unless the trusted policy changes. Builds exceeding the
safe defaults will require an explicit configuration change. Manual patch
application is less convenient but keeps the original directory outside the
agent's write path.

## Rejected recommendations

### Authorize `EvalSymlinks` plus cleaned path comparison

Rejected because it is Go-specific and separates checking from use, leaving a
path-replacement race. Real-path comparison may be a diagnostic but is not the
permission mechanism.

### Declare file-content injection out of scope

Rejected because a manipulated model can misuse legitimate typed actions. The
design contains those effects rather than claiming the injection class is gone.
