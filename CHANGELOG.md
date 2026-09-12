# Changelog

## 0.1.0b3 - 2026-09-12

- Renamed the PyPI distribution from `under-llm-governance` to `warrant-llm`.
- Preserved the `ulg` Python import package and command-line entry point for
  compatibility.
- Updated trusted publishing, public-install verification, documentation, and
  artifact checks for the new distribution name.

## 0.1.0b2 - 2026-09-09

- Removed unrelated landing-site assets accidentally included in the
  `0.1.0b1` source distribution; they were never present in the wheel.
- Corrected project and support links after the repository moved to
  `aminobutyric/warrant`.
- Restricted source-distribution inputs and added a matching artifact allowlist
  so unrelated top-level content fails the release gate.

## 0.1.0b1 - 2026-09-09

- Added disposable read-only inspection and reviewed patch generation through a
  local Ollama model.
- Added durable task recovery, bounded scoped approvals, redacted audit views,
  and explicit cleanup.
- Added an immutable, offline, resource-bounded rootless-Docker runner for
  Python, Go, and JavaScript verification.
- Added adversarial security acceptance coverage, artifact verification,
  dependency auditing, trusted PyPI publishing, and release provenance.

Known limitations are documented in [the beta operations guide](docs/operations.md).
