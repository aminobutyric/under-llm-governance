# Offline runner image

The Phase 3 runner contains Python 3.13, pytest 8.4.2, Ruff 0.16.1, and the
Debian Bookworm `golang-go` and `nodejs` packages. Its Python base is
pinned by registry digest in `Dockerfile`. The completed local image is pinned
again by its image ID in trusted application configuration.

Build it only through the rootless daemon. This form works from any directory:

```console
export ULG_REPO=/home/amin-mth/Projects/Personal/under-llm-governance
docker build --pull=false --tag ulg-runner:phase3 "$ULG_REPO/runner"
docker image inspect ulg-runner:phase3 --format '{{.Id}}'
```

Copy the returned `sha256:...` value into `sandbox.image_digest` in the trusted
policy. Runtime execution uses that digest with `--pull never`; the mutable tag
is used only to check that the locally built image still has the configured ID.

The image records its installed-package inventories at:

- `/usr/share/ulg-runner/dpkg-sbom.tsv`
- `/usr/share/ulg-runner/python-sbom.json`

Inspect them without running project code:

```console
docker run --rm --entrypoint /bin/cat ulg-runner:phase3 \
  /usr/share/ulg-runner/dpkg-sbom.tsv
docker run --rm --entrypoint /bin/cat ulg-runner:phase3 \
  /usr/share/ulg-runner/python-sbom.json
```

Those inventories describe the exact local build. Rebuilding after repository
packages change can produce a different image ID and requires an explicit
trusted-policy update.
