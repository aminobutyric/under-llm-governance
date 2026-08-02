# Development Plan

## Delivery strategy

Build capability in small increments. Every phase must preserve the security
invariants from the previous phase and finish with automated acceptance tests.
Later phases may add permissions only behind explicit policy.

The locked implementation target is Python 3.11+ on Linux, managed with `uv` and
a committed lockfile. Use the standard library when practical, validate external
data with strict Pydantic models, pin third-party dependencies, and keep the
trusted controller separate from commands running in the sandbox.

## Phase 0: executable specification

Goal: turn the architecture into stable contracts before granting any model an
effectful tool.

Deliverables:

- Create `pyproject.toml`, `uv.lock`, the `src/ulg` package, and the `ulg` entry
  point.
- Define versioned configuration, action, result, decision, approval, and audit
  models with strict Pydantic validation and rejection of unknown fields.
- Implement strict TOML configuration parsing with safe built-in defaults.
- Define interfaces for the model adapter, policy engine, tools, workspace
  manager, sandbox runner, approval service, and audit sink.
- Add structured errors and task/correlation identifiers.
- Add executable contract tests for the locked sandbox and workspace-generation
  boundaries, documenting any implementation limitation as a new ADR.
- Establish Ruff, mypy, pytest, Hypothesis, dependency scanning, and CI.

Exit criteria:

- Invalid and unknown configuration is rejected.
- Schema round-trip and malformed-input tests pass.
- A dry-run action can flow through controller, policy, and audit components
  without touching the filesystem or starting a process.
- The trusted/untrusted boundary is visible in package dependencies.

## Phase 1: read-only coding assistant

Goal: let Ollama inspect a selected project without executing code or modifying
files.

Deliverables:

- Implement the Ollama chat/tool-calling adapter with endpoint validation,
  timeouts, response-size limits, and cancellation.
- Implement workspace selection and a read-only task snapshot.
- Exclude built-in secret patterns, user patterns, `.git`, and gitignored paths
  before reading bytes into the task copy.
- Implement `list_files`, `read_file`, and `search_text`.
- Enforce relative-path, file-type, size, depth, count, and output limits.
- Implement descriptor-relative, no-follow path access and adversarial race
  tests; path-string comparison is not accepted as containment.
- Add the bounded controller loop with maximum steps and repeated-call
  detection.
- Add JSON-lines audit logging with redaction.
- Provide `ulg inspect --workspace PATH --task TEXT`.

Exit criteria:

- The assistant can explain a small repository and cite the files it read.
- Traversal, symlink, special-file, oversized-file, and race tests fail closed.
- Stopping the CLI cancels the active Ollama request.
- No subprocess or network capability other than controller-to-Ollama exists.

## Phase 2: safe editing in a disposable workspace

Goal: produce reviewable changes without granting write access to the original
project.

Deliverables:

- Create application-owned, per-task workspace copies with quotas and cleanup.
- Record a source manifest used for diff generation, copy verification, and
  audit metadata.
- Implement generation-based `apply_patch`: dry-run all hunks, build an
  unreferenced result, and switch task state only after full validation.
- Implement `show_diff` and a concise changed-file summary.
- Prevent tools from modifying trusted configuration or runtime state.
- Export a validated patch artifact for manual review. No promotion operation is
  implemented inside the controller.
- Destroy task workspaces after patch export or discard. Retention requires an
  explicit user choice and remains bounded.

Exit criteria:

- A task can edit several files and produce a correct diff.
- The original remains unchanged throughout this phase.
- Patch export contains only paths and changes represented in the reviewed diff.
- Cancellation or model failure leaves the last complete generation available
  for bounded export-or-discard handling; incomplete generations are removed.

## Phase 3: offline sandboxed verification

Goal: run project-defined checks without allowing arbitrary host execution.

Deliverables:

- Build a pinned runner image and document its software bill of materials.
- Implement the rootless Docker sandbox backend with a fixed security profile.
- Introduce trusted `run_task` recipes for test, lint, and format. The model
  selects only a recipe name; it cannot construct or alter commands.
- Pass commands as argument arrays; do not interpolate model strings into a
  shell.
- Add clean environment construction and bounded stdin/stdout/stderr capture.
- Default to 512 MiB memory, 1 CPU, 128 PIDs, 60 seconds wall-clock, 128 MiB
  temporary storage, and 1 MiB combined stdout/stderr. Values are finite and
  strictly validated from trusted configuration.
- Kill complete process trees on cancellation or timeout.
- Record the image digest and effective sandbox settings in audit events.

Exit criteria:

- Representative Go, Python, and JavaScript checks run offline when their
  dependencies are already present in the image or workspace.
- Network, capability, device, host-path, Docker-socket, and namespace escape
  tests fail.
- Fork-bomb, infinite-loop, disk-fill, and output-flood tests terminate within
  their configured limits without destabilizing the host.

## Phase 4: approvals and usable task workflow

Goal: make security decisions understandable without making the tool painful to
use.

Deliverables:

- Implement terminal approval prompts rendered exclusively from normalized
  controller data.
- Bind grants to an action or exact recipe digest, task, maximum uses, and
  expiry. Configuration changes revoke existing grants.
- Keep reads, searches, diffs, and small disposable-workspace patches automatic
  and logged; require grants for recipes and policy-threshold patch operations.
- Add plan, execute, review, retry, cancel, export, and discard task states.
- Explain policy denials to the model without revealing sensitive host details.
- Add `ulg run`, `ulg resume`, `ulg diff`, `ulg audit`, and `ulg clean` commands.
- Produce a final report separating attempted actions, executed actions,
  verified results, pending changes, and user approvals.

Exit criteria:

- Approval replay and prompt-forging tests fail.
- No controller or model operation can write to the original directory.
- A user can understand exactly what changed and which checks actually ran.
- Interruptions and restarts do not accidentally repeat effectful actions.
- Audit records reconstruct the complete task lifecycle.

## Phase 5: controlled dependency and network access

Goal: support real projects that need missing dependencies without providing
general-purpose exfiltration capability.

This phase begins only after the offline MVP is stable.

Deliverables:

- Separate dependency preparation from agent command execution.
- Design an allowlisting proxy or repository-specific fetch service.
- Require approval showing package ecosystem, requested artifacts, source,
  destination, and whether lifecycle scripts will execute.
- Add checksums, lockfile enforcement, cache isolation, download limits, and
  provenance in audit records.
- Keep general outbound networking unavailable to the task sandbox.
- Add policy for local services; loopback is not automatically trusted.

Exit criteria:

- A dependency can be fetched only from an allowed source through the controlled
  path.
- Direct DNS and outbound connections from task code still fail.
- Package lifecycle scripts cannot gain more authority than offline test code.
- The user can reproduce which artifacts entered a task.

## Phase 6: hardening and release

Goal: make the single-user local tool dependable enough for regular use.

Deliverables:

- Fuzz parsers, action normalization, path handling, patch application, policy,
  and approval serialization.
- Add fault-injection and crash-recovery tests.
- Red-team prompt injection through files, filenames, command output, and model
  tool arguments.
- Evaluate Landlock as a second filesystem boundary and document its kernel
  compatibility behavior.
- Sign release artifacts and publish checksums and an SBOM.
- Write installation, upgrade, incident-response, and data-retention guides.
- Commission an independent security review before any multi-user mode.

Exit criteria:

- All adversarial acceptance tests in `docs/security-model.md` pass.
- Security defaults cannot be disabled accidentally through project content.
- A clean machine can install and run a pinned release reproducibly.
- Known limitations and residual risks are documented next to the release.

## Initial milestone backlog

The first implementation milestone should contain these issues, in order:

1. Initialize the locked `uv`/`src` Python project and CLI skeleton.
2. Define action and policy-decision types.
3. Load and strictly validate policy configuration.
4. Implement append-only JSONL audit events with redaction hooks.
5. Implement a fake model adapter for deterministic tests.
6. Implement the dry-run controller loop.
7. Implement secure workspace-root opening and relative path resolution.
8. Implement bounded `list_files`.
9. Implement bounded `read_file`.
10. Implement bounded `search_text`.
11. Implement the Ollama adapter.
12. Add adversarial filesystem fixtures and end-to-end read-only tests.

## Engineering rules

- No model-controlled value may become a shell command, host path, container
  image, mount, environment variable name, or sandbox security option without a
  typed allowlist and validation.
- Never use `shell=True`; execute trusted argument arrays only.
- Add a negative test with every new permission.
- Prefer capabilities that are absent over capabilities that are merely denied
  by a prompt.
- Keep policy evaluation pure where possible and test decisions as tables.
- Pin container images by digest for releases.
- Record verification evidence; do not report a test as passing based only on
  model narration.
- Stop and revise the architecture when a feature needs a broadly privileged
  escape hatch.
