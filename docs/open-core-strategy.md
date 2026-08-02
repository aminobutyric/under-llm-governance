# Open-core strategy

## Position

Under LLM Governance should begin as a useful open-source local tool under
MPL-2.0. A future commercial offering should sell organizational coordination,
deployment, compliance, and support—not remove safety from the community
edition or impose artificial local-use limits.

This is a product boundary, not legal advice. The boundary should be reviewed
by licensing counsel before proprietary modules are distributed.

## Community edition: always open

The public repository should contain a complete, production-usable single-user
local agent, including:

- the trusted controller and typed action protocol;
- policy evaluation, scoped approvals, and security defaults;
- local model adapters, starting with Ollama;
- disposable workspaces, patch review, and export;
- the rootless offline sandbox and resource limits;
- local audit events and JSONL storage;
- the CLI, configuration schema, extension contracts, tests, and security
  documentation.

Security fixes and baseline hardening belong in the community edition. Core
security should not become a reason users must buy an enterprise license.

## Possible enterprise offering

Enterprise modules can live in separate files, packages, or services and focus
on multi-user operational needs:

- SSO, SAML/OIDC, SCIM, organization roles, and separation of duties;
- a multi-user control plane and fleet-wide policy distribution;
- signed policy bundles, approval routing, and change management;
- centralized retention, search, SIEM export, and tamper-evidence services;
- managed runners, high availability, upgrades, and deployment automation;
- compliance evidence packs, organization reporting, and admin dashboards;
- vendor support, security response commitments, training, and professional
  services.

Enterprise code should depend on stable public interfaces in the community
core. It should not copy community files into a proprietary tree merely to
avoid sharing modifications.

## Licensing boundary

MPL-2.0 is file-level copyleft. If MPL-covered files are modified and the
result is distributed, the covered source files remain subject to MPL-2.0.
Separate new files may be combined with the MPL code in a larger work under
other terms. Keep proprietary modules visibly separate and maintain a clear
source-file inventory.

MPL-2.0 does not prohibit commercial use, hosting, forks, or competing
offerings. The defensible commercial value must therefore come from execution:
trusted releases, integrations, operational tooling, support, reputation, and
the speed of the project—not from assuming the license prevents competition.

Before accepting substantial outside contributions, adopt a lightweight DCO or
another explicit contribution policy. A contributor license agreement is only
needed if a concrete relicensing or dual-licensing strategy justifies its added
friction. Project names and logos should be governed by a separate trademark
policy if they become commercially important.

## Repository boundary

Start with two clear units if an enterprise product is eventually built:

```text
under-llm-governance/          MPL-2.0 community core and public contracts
ulg-enterprise/                separately licensed organization features
```

Do not create the enterprise repository before there are real enterprise users
and a feature that belongs there. Until then, document requirements publicly
and keep attention on making the community core trustworthy.

## Commercialization gates

1. Complete a credible single-user local MVP and publish its threat model.
2. Build a real user community and learn which team problems repeat.
3. Validate willingness to pay for one organizational feature or support.
4. Obtain a license-boundary review before distributing proprietary code.
5. Create the separate enterprise package only when the boundary is concrete.

Revenue can start earlier through support, security reviews, integration work,
and hosted pilots without prematurely splitting the codebase.

## Decision test for future features

Put a feature in the community core when it is necessary for safe local use,
interoperability, trust, or a healthy extension ecosystem. Consider enterprise
only when the feature primarily coordinates multiple people or machines,
enforces organization-level governance, or provides a managed service.

