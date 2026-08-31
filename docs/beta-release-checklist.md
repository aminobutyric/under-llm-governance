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

The all-zero runner digest is deliberately an unreleased-candidate sentinel. It
must be replaced in Milestone 3; no artifact containing it may be published.

## Milestone 2: security acceptance

- [ ] Map all 15 release security cases to automated tests.
- [ ] Require both containment and useful audit evidence for every case.
- [ ] Complete the missing prompt-injection, approval, lifecycle-script, and
      Git-hook scenarios.
- [ ] Prove interruption and restart do not repeat effectful actions.
- [ ] Confirm every workflow leaves the selected original project unchanged.

## Milestone 3: immutable runner candidate

- [ ] Build the Linux amd64 runner candidate from the release commit.
- [ ] Publish the candidate to GHCR and record its repository digest.
- [ ] Replace the all-zero policy sentinel with that exact digest.
- [ ] Run all live rootless-Docker acceptance groups against the candidate.
- [ ] Record installed-package inventories and acceptance evidence.

## Milestone 4: publishable beta

- [ ] Add the dependency-security release check to CI.
- [ ] Add build, artifact inspection, and release workflows.
- [ ] Document limitations, retention, recovery, upgrade, and issue reporting.
- [ ] Configure trusted PyPI publishing and GitHub release permissions.
- [ ] Build from the release tag, verify artifacts, publish PyPI and GitHub
      prereleases, and verify a fresh public install.
- [ ] Publish the checksums and announce the beta support channel.

## Release stop conditions

Do not publish if the runner digest is the all-zero sentinel, any required
security case fails, the original-project integrity check fails, artifact
metadata differs from `0.1.0b1`, or a clean supported-Python install fails.
