# Internal packages

The implementation is planned around these packages:

| Package | Responsibility |
|---|---|
| `controller` | Task state machine and bounded agent loop |
| `model` | Provider-neutral model contracts |
| `model/ollama` | Local Ollama adapter |
| `action` | Versioned action and result types |
| `policy` | Pure, deterministic allow/ask/deny evaluation |
| `approval` | Exact, expiring, single-use approvals |
| `tools` | Narrow filesystem and verification operations |
| `workspace` | Disposable task copies and safe promotion |
| `sandbox` | Resource-limited offline command execution |
| `audit` | Structured events and secret redaction |
| `config` | Strict configuration parsing and defaults |

Packages should depend inward on small contracts. In particular, `policy` must
not depend on Ollama, and task code must never run in the controller process.
