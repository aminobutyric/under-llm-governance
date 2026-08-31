# Offline runner image

The Phase 3 runner contains Python 3.13, pytest 8.4.2, Ruff 0.16.1, and the
Debian Bookworm `golang-go` and `nodejs` packages. Its Python base is
pinned by registry digest in `Dockerfile`. Published runners are pinned again
by their immutable GHCR repository digest in trusted application configuration.

Build it only through the rootless daemon. This form works from any directory:

```console
export ULG_REPO=/home/amin-mth/Projects/Personal/under-llm-governance
docker build --pull=false \
  --tag ghcr.io/aminobutyric/under-llm-governance-runner:0.1.0b1 \
  "$ULG_REPO/runner"
```

Milestone 3 will push this candidate, resolve its GHCR digest, complete live
acceptance, and replace the all-zero sentinel in `sandbox.image`. Runtime
execution and verification both use that exact `name@sha256:...` reference with
`--pull never`; a mutable tag is never accepted as trusted configuration.

The image records its installed-package inventories at:

- `/usr/share/ulg-runner/dpkg-sbom.tsv`
- `/usr/share/ulg-runner/python-sbom.json`

Inspect them without running project code:

```console
docker run --rm --entrypoint /bin/cat \
  ghcr.io/aminobutyric/under-llm-governance-runner:0.1.0b1 \
  /usr/share/ulg-runner/dpkg-sbom.tsv
docker run --rm --entrypoint /bin/cat \
  ghcr.io/aminobutyric/under-llm-governance-runner:0.1.0b1 \
  /usr/share/ulg-runner/python-sbom.json
```

Those inventories describe the exact candidate build. Any rebuild can produce a
different registry digest and requires acceptance plus an explicit
trusted-policy update.
