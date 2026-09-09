# Python source layout

The `src/ulg` package uses these trust boundaries:

| Package | Responsibility |
|---|---|
| `controller` | Bounded, synchronous task state machine |
| `actions` | Strict, versioned action and result models |
| `model` | Provider contract plus fake and Ollama adapters |
| `policy` | Pure deterministic allow/ask/deny evaluation |
| `approval` | Exact actions and bounded recipe grants |
| `tools` | Narrow filesystem, patch, diff, and recipe operations |
| `workspace` | Exclusions, copies, generations, and patch export |
| `sandbox` | Rootless, resource-limited offline execution |
| `audit` | Audit-safe events, JSONL sink, and strict redacted lifecycle reader |
| `tasks` | Crash-consistent lifecycle, effect journal, and safe cleanup metadata |
| `config` | Strict TOML parsing and layered restrictions |

Task code never runs in the controller process. `policy` does not depend on a
model provider, and raw untrusted payloads do not cross into the audit sink.

The current executable slice includes strict action/configuration models, the
deterministic baseline policy, audit-safe lifecycle events, fake and Ollama model
adapters, secure disposable snapshots, bounded read-only tools, atomic patch
generations, reviewed patch export, `ulg inspect`, `ulg run`, rootless Docker
sandbox preflight, and direct trusted-recipe acceptance. Model-triggered
recipe execution now crosses normalized terminal approval, durable scoped grant
consumption, at-most-once effect scheduling, sandbox execution, and allowlisted
audit events. Atomic task state, verified generation recovery, restart-safe
`resume`, explicit `discard`, and legacy recovery export are implemented.
Controller-owned `diff`, `audit`, and exact-target `clean` commands provide
bounded review, redacted lifecycle summaries, age/size previews, and protected
retained-work deletion. Successful coding output includes both the separate
model summary and an audit-derived execution summary.
