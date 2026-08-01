# Security Model

## Security objective

Limit the worst possible result of a hallucinated, manipulated, or malicious
model action to the explicitly granted scope of one task.

The design does not attempt to prove that model-generated code is correct. It
aims to prevent that code, and the process producing it, from gaining ambient
authority over the host.

## Protected assets

- Files outside the selected project.
- The original project and its untracked files.
- SSH keys, tokens, cookies, password stores, and environment secrets.
- Host processes, devices, kernel interfaces, and container control sockets.
- Local and remote network services.
- CPU, memory, disk, process table, and user attention.
- Integrity of audit records and approval prompts.

## Untrusted inputs

- User task text.
- Every model response, including valid structured output.
- Source files, documentation, images, lockfiles, and repository metadata.
- Compiler, test, linter, Git, and package-manager output.
- Downloaded dependencies and their lifecycle scripts.
- Existing symlinks, special files, Git hooks, and configuration in a project.

Local inference changes privacy and availability characteristics, but does not
make model decisions trustworthy.

## Threat actors and failure modes

The initial single-user threat model covers:

- accidental model hallucination;
- direct prompt injection in the user request;
- indirect prompt injection embedded in repository content or tool output;
- malicious code already present in the selected project;
- a dependency or build script attempting to escape its expected scope;
- malformed or adversarial tool arguments;
- denial of service through loops, process creation, output, memory, or disk;
- mistakes in path validation or approval presentation.

Compromise of the host kernel, Docker runtime, or trusted controller is outside
the MVP guarantee, but the design minimizes their exposed interfaces.

## Non-negotiable controls

### Filesystem containment

- Canonical paths are not authorized using string prefixes.
- The trusted code opens a workspace root and resolves relative descendants
  from that root.
- Absolute paths, traversal, magic links, cross-mount traversal, symlinks, and
  non-regular files are rejected unless a later policy explicitly supports
  them.
- Validation and file use must not be separate operations vulnerable to a
  time-of-check/time-of-use race.
- The original workspace is not the sandbox's writable working directory.

### Process containment

- No root, setuid escalation, added capabilities, privileged containers, host
  namespaces, devices, or control sockets.
- Network is absent by default.
- Resource and time limits are mandatory, not optional configuration.
- A clean environment is constructed from an allowlist.
- Sandbox termination kills the complete process tree.

### Authorization

- Tool schemas use explicit types, bounds, enums, and rejection of unknowns.
- Policy decisions are deterministic and default to deny.
- High-impact approval identifies the exact action and cannot be forged by
  model-generated prose.
- An approval is scoped to one normalized action and expires after use or time.
- The model cannot edit policy, audit configuration, sandbox configuration, or
  its own trusted instructions through workspace tools.

### Observability

- Proposed, denied, approved, executed, failed, and timed-out actions are
  recorded.
- Logs are append-oriented and include task and correlation identifiers.
- File contents, prompts, output, and environment values are bounded and
  redacted before logging.
- The final user report distinguishes model claims from verified command
  results.

## Initial permission matrix

| Capability | MVP policy | Rationale |
|---|---|---|
| Read a regular file in task copy | Allow with size limit | Required for coding |
| Write through a validated patch | Allow and audit | Recoverable in disposable copy |
| Run a configured offline check | Allow and audit | Required for verification |
| Modify original directory | Ask during promotion | Crosses task boundary |
| Delete a large set of files | Ask or deny | High integrity impact |
| Execute arbitrary shell | Deny | Excessive functionality for MVP |
| Access network | Deny | Prevent exfiltration and downloads |
| Read host home or environment | Deny | Prevent secret disclosure |
| Install packages | Deny | Executes untrusted code and needs network |
| Git commit | Deny initially | Not needed to produce a reviewable diff |
| Git push, publish, deploy | Deny | External side effect |
| Access Docker socket or devices | Deny | Equivalent to host-level authority |

## Adversarial acceptance tests

Before an MVP release, automated tests must demonstrate failure of:

1. `../../` and absolute-path reads and writes.
2. A workspace symlink pointing to `/etc/passwd` or a file in the user's home.
3. A path replaced with a symlink between validation and use.
4. Access through `/proc/*/fd`, Unix sockets, devices, or other special files.
5. A README instructing the model to reveal secrets or bypass policy.
6. `curl`, DNS, raw sockets, or connection attempts to Ollama and localhost.
7. Fork bombs, detached children, infinite loops, and excessive file creation.
8. Excessive stdout/stderr and binary output.
9. Git hooks and package lifecycle scripts attempting host access.
10. Model-provided container flags, images, mounts, or environment variables.
11. Reuse, expansion, or misleading display of a previously approved action.
12. Promotion when the original directory changed during the task.

Each test should assert both containment and a useful audit event.

## Known limitations of the MVP

- Containers share the host kernel and are not a perfect isolation boundary.
- Offline execution can still damage everything writable inside its task copy.
- A safe sandbox does not make generated code free of vulnerabilities.
- Users can still approve a harmful action; approval presentation must therefore
  be precise and resistant to model-controlled wording.
- A single-user local design is not suitable as-is for an internet-facing or
  multi-tenant service.
