# Beta release procedure

Releases are immutable and tag-driven. The version in `src/ulg/__init__.py` and
the annotated tag `vVERSION` must match. Never retag or overwrite a published
PyPI version.

## One-time repository setup

Create a PyPI trusted publisher with these exact values:

- PyPI project: `warrant-llm`
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
   git tag -a v0.1.0b3 -m "Warrant v0.1.0b3"
   git push origin v0.1.0b3
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

## Distribution-name migration

Versions `0.1.0b1` and `0.1.0b2` were published under the former PyPI
distribution name `under-llm-governance`. Do not delete that project until
`warrant-llm==0.1.0b3` has completed the workflow above and passed an
independent public install. PyPI projects cannot be renamed in place, and the
old release tags remain immutable historical records.

After the replacement is verified, remove the former PyPI project only through
its project settings while signed in as an owner. Deletion is permanent and
must not be performed as part of the automated release workflow.
