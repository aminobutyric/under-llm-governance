# Beta release procedure

Releases are immutable and tag-driven. The version in `src/ulg/__init__.py` and
the annotated tag `vVERSION` must match. Never retag or overwrite a published
PyPI version.

## One-time repository setup

Create a PyPI trusted publisher with these exact values:

- PyPI project: `under-llm-governance`
- GitHub owner: `aminobutyric`
- Repository: `warrant`
- Workflow: `release.yml`
- Environment: `pypi`

For the first upload, create a pending publisher from the PyPI account's
publishing page. In GitHub, create the `pypi` environment, restrict deployment
to protected tags matching `v*`, and optionally require a maintainer approval.
The workflow grants only `id-token: write` to the PyPI job and `contents: write`
to the GitHub release job; no long-lived PyPI token is used.

## Release gates

1. Merge the beta branch into `release` and require a green CI run.
2. Confirm the tree is clean and the public runner digest in the packaged policy
   matches the accepted runner evidence.
3. Create an annotated tag from the exact `release` commit and push it:

   ```console
   git tag -a v0.1.0b2 -m "Under LLM Governance v0.1.0b2"
   git push origin v0.1.0b2
   ```

4. Approve the protected `pypi` environment deployment, if configured.
5. Confirm the release workflow verifies Python 3.11/3.13, inspects both
   artifacts, smoke-installs the wheel, attests provenance, publishes to PyPI,
   clean-installs that exact public PyPI version on both supported endpoint
   Pythons, and creates a GitHub prerelease with `SHA256SUMS`.
6. On a clean public machine, independently install the exact PyPI version, run
   `ulg init`, `ulg dry-run`, pull the configured runner by digest, and run
   `ulg sandbox-preflight`.

If any gate fails, leave the tag for diagnosis but do not manually upload a
different artifact under the same version. Fix the source, increment the beta
version, and release a new tag.

## `0.1.0b1` recovery

Do not delete or move `v0.1.0b1`, and do not rerun its failed release workflow:
PyPI already published artifacts from that immutable tag. After `0.1.0b2` is
public and its complete workflow succeeds, yank `0.1.0b1` on PyPI with the
reason `Source distribution included unrelated site assets; use 0.1.0b2`.
Yanking preserves the audit record and exact-version reproducibility while
directing normal installers to the corrected beta.
