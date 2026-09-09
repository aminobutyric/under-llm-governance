# Security policy

## Supported versions

`0.1.x` beta releases receive security fixes. Unreleased snapshots and older
versions are supported only when a maintainer explicitly says so.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use the repository's
[private vulnerability report](https://github.com/aminobutyric/under-llm-governance/security/advisories/new)
and include the affected version, operating system, reproduction steps, and
security impact. Remove credentials, proprietary source, model prompts, audit
records, and other sensitive data before attaching diagnostics.

The project is maintained on a best-effort basis and has no response-time SLA.
We will acknowledge a usable report, investigate it privately, and coordinate
disclosure and a fixed release when warranted.

## Release integrity

Official Python packages are published as `under-llm-governance` on PyPI by the
tag-triggered GitHub Actions workflow using trusted publishing. GitHub
prereleases contain the same wheel and source distribution plus `SHA256SUMS`.
The sandbox runner is selected by the exact GHCR digest in the packaged policy;
tags are not trusted as execution identities.
