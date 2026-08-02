# Python source layout

Phase 0 establishes the `src/ulg` package with these boundaries:

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
| `audit` | Audit-safe events, pre-write redaction, and JSONL sink |
| `config` | Strict TOML parsing and layered restrictions |

Task code never runs in the controller process. `policy` does not depend on a
model provider, and raw untrusted payloads do not cross into the audit sink.

The current executable slice includes strict action/configuration models, the
deterministic baseline policy, audit-safe lifecycle events, fake and Ollama model
adapters, secure disposable snapshots, bounded read-only tools, atomic patch
generations, reviewed patch export, `ulg inspect`, and `ulg run`. Sandbox and
approval packages remain contracts until their security tests are implemented
in the next MVP phases.
