# v0.1 beta release checklist

This checklist tracks the shortest path to the public `v0.1.0b1` beta. The
release remains Linux amd64, local Ollama, rootless Docker, PyPI plus GitHub, and
an immutable GHCR runner. The beta collects no telemetry.

## Milestone 1: release foundation

- [x] Use `0.1.0b1` as the single package and CLI version source.
- [x] Package the trusted policy template in both wheel and source distribution.
- [x] Add `ulg init` with the `qwen3-coder:30b` reference model.
- [x] Create and replace user policy files privately and atomically.
- [x] Discover policy by `--config`, `ULG_CONFIG`, then the XDG user path.
- [x] Require an immutable digest-qualified GHCR runner reference.
- [x] Verify and execute the exact configured registry digest.
- [x] Build the wheel and source distribution successfully.
- [x] Clean-install and smoke-test the wheel on Python 3.11 and 3.13.
- [x] Document the installed quick start and runner-digest transition.

The trusted policy records the published candidate digest, and an anonymous
digest-qualified GHCR pull has passed.

## Milestone 2: security acceptance

- [x] Map all 15 release security cases to automated tests.
- [x] Require both containment and useful audit evidence for every case.
- [x] Complete the missing prompt-injection, approval, lifecycle-script, and
      Git-hook scenarios.
- [x] Prove interruption and restart do not repeat effectful actions.
- [x] Confirm every workflow leaves the selected original project unchanged.

## Milestone 3: immutable runner candidate

- [x] Build the Linux amd64 runner candidate from the committed candidate tree.
- [x] Publish the candidate to GHCR and record its repository digest.
- [x] Replace the policy placeholder with that exact candidate digest.
- [x] Run all live rootless-Docker acceptance groups against the candidate.
- [x] Record installed-package inventories and acceptance evidence.

## Milestone 4: publishable beta

- [x] Add the dependency-security release check to CI.
- [x] Add build, artifact inspection, and release workflows.
- [x] Document limitations, retention, recovery, upgrade, and issue reporting.
- [ ] Configure trusted PyPI publishing and GitHub release permissions.
- [ ] Build from the release tag, verify artifacts, publish PyPI and GitHub
      prereleases, and verify a fresh public install.
- [ ] Publish the checksums and announce the beta support channel.

The repository-side OIDC and least-privilege release permissions are ready.
Trusted publishing still requires the one-time PyPI/GitHub environment setup in
the [release procedure](releasing.md); publication items remain unchecked until
the tag workflow and a clean public install succeed.

## Release stop conditions

Do not publish if the configured runner is unavailable from GHCR, any required
security case fails, the original-project integrity check fails, artifact
metadata differs from `0.1.0b1`, or a clean supported-Python install fails.

The runner is public and anonymously pullable by its configured digest. The
remaining stop conditions are covered by the committed-tree and Milestone 4
release gates.
