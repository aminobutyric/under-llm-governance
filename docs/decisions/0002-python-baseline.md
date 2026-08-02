# ADR 0002: Use Python for the trusted controller

- Status: accepted
- Date: 2026-08-02

## Context

The controller needs fast iteration, strong validation at untrusted boundaries,
good local-model integration, and extensive adversarial testing. The primary
developer is more productive in Python. Go would simplify static distribution
and some low-level Linux integration, but language choice is not the sandbox or
authorization boundary.

## Decision

Use Python 3.11 or newer with:

- a `src/ulg` package layout and `ulg` console entry point;
- `uv`, `pyproject.toml`, and a committed `uv.lock`;
- strict Pydantic models for external data and versioned actions;
- the official Ollama client behind a provider-neutral interface;
- Ruff, mypy, pytest, and Hypothesis;
- synchronous single-task orchestration for the MVP;
- standard-library subprocess execution with argument arrays and `shell=False`.

The model adapter, policy engine, filesystem tools, sandbox runner, approval
service, and audit sink remain separate packages. No agent framework is part of
the trusted baseline.

## Consequences

Development and security testing should move quickly, and the model integration
stays small. Runtime typing must still be explicit: annotations alone do not
validate data. Packaging is less self-contained than a Go binary. Low-level path
operations require careful descriptor-relative Python code and may later be
replaced behind the same interface by a small audited native helper.

## Rejected alternatives

### Go for the complete controller

Technically viable, but its deployment advantages do not outweigh current
developer fluency and iteration speed for this local MVP.

### General agent framework

Rejected because implicit dispatch, middleware, memory, and tool behavior would
increase the trusted computing base before the permission model is proven.
