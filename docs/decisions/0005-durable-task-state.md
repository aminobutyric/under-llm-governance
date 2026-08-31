# ADR 0005: durable task state uses at-most-once effect scheduling

## Status

Accepted for the single-user local MVP.

## Context

Disposable generations made controlled failures recoverable, but controller and
grant state existed only in memory. A process restart could not safely determine
whether an approved effect had started, whether a patch generation had published,
or how many uses remained on a recipe grant.

Persisting the complete model conversation would retain repository contents and
tool output that are deliberately excluded from audit data. Automatically
rerunning an action whose outcome is uncertain would also violate the approval
and replay guarantees.

## Decision

- Store a strict, bounded task record beneath application state with mode `0600`.
  It contains the original task text, trusted absolute paths, complete
  configuration digest, model name, current generation, lifecycle phase, and a
  bounded effect journal. It does not contain repository contents or tool output.
- Commit state with a same-directory temporary file, file synchronization, atomic
  replace, directory synchronization, and a monotonic revision. Use a non-blocking
  `flock` lease to prevent concurrent execution of the same task.
- Persist complete grant records, including uses and consumed action identifiers.
  Issuance and consumption write the candidate durable snapshot before changing
  executable in-memory state.
- Persist an effect marker after authorization but before invoking `apply_patch`
  or `run_task`. This creates at-most-once scheduling across controller restarts.
- Recover patches by walking consecutive manifest-verified generations. A final
  directory without a complete manifest is unpublished and removed; a complete
  successor whose parent digest matches is adopted.
- Treat an interrupted sandbox execution as outcome-unknown. Record that outcome,
  revoke grants for its recipe, and require a fresh proposal and approval rather
  than silently repeating it.
- Resume with a new bounded model conversation based on the original task and the
  current verified workspace. The model must re-inspect relevant files.
- Retain failed and cancelled tasks by default. `--failure-mode recover` keeps the
  previous bounded export-and-discard behavior, and `ulg discard` explicitly
  destroys retained generations and grants.

## Consequences

Resume is robust to completed patch publication and fails closed on corrupt state,
broken manifest chains, changed trusted configuration, lease contention, and
uncertain command outcomes. A consumed grant use may be lost if the controller
stops between durable consumption and effect scheduling; this is preferable to
executing twice. Command results cannot always be recovered after abrupt process
death and are therefore reported as unknown instead of inferred.

Task state contains the user's original request and trusted filesystem paths. It
is private application state, not an audit event, and must be covered by retention
and cleanup documentation. The JSON files are crash-consistent but not
tamper-evident; hash chaining and stronger multi-process transaction machinery
remain outside the MVP claim.
