# Beta operations guide

## Supported environment and limitations

The `v0.1` beta supports one local user and one task process at a time on Linux
with Python 3.11–3.13, `uv`, rootless Docker using cgroup v2/systemd, and a
locally bound Ollama server. The published runner is Linux amd64. Other
architectures, Docker Desktop/rootful Docker, remote model endpoints, concurrent
task operators, and Windows/macOS hosts are not supported.

This is a defensive boundary for a local coding workflow, not a hardened
multi-tenant service. It does not install dependencies, enable sandbox network
access, apply generated patches, push Git, deploy, or manage credentials. Model
quality depends on the selected local Ollama model. The beta collects no
telemetry.

## Install and initialize

```console
uv tool install warrant-llm==0.1.0b3
ulg init
ollama pull qwen3-coder:30b
ulg dry-run
ulg sandbox-preflight
```

The policy lives at `$XDG_CONFIG_HOME/ulg/policy.toml` or
`~/.config/ulg/policy.toml`. Treat it as trusted security configuration. Keep a
private backup before editing it and never accept a model-generated replacement.
`ulg init --force` replaces the existing file atomically, so use it only when
you intend to reset local policy customizations.

## Retention and disk usage

Application state lives at `$XDG_STATE_HOME/ulg` or `~/.local/state/ulg` and is
private to the user. A failed or cancelled coding task retains its verified
workspace generation, strict task record, bounded effect journal, scoped-grant
records, and redacted audit log so it can be reviewed or resumed. Successful
patch export and explicit discard remove workspace generations and grants but
retain the small lifecycle record and audit until cleanup.

There is no automatic retention timer in `v0.1`. Review exact task IDs and remove
old completed records explicitly:

```console
ulg audit TASK_ID
ulg clean TASK_ID --older-than-days 30 --yes
```

Resumable tasks are protected. Deleting one requires both its exact ID and
`--include-retained`.

## Recovery and incident handling

When `ulg run` fails or is interrupted, copy the printed task ID and inspect the
controller-owned views:

```console
ulg audit TASK_ID
ulg diff TASK_ID
ulg resume TASK_ID
```

Resume verifies the complete manifest chain and the trusted-policy digest. It
will not replay a recorded patch publication; an interrupted sandbox result is
marked unknown and its recipe grant is revoked. If the policy changed, inspect
or discard the task instead of bypassing the refusal:

```console
ulg discard TASK_ID
```

If containment or credential exposure is suspected, stop the task, do not
resume it, revoke affected credentials outside ULG, preserve only sanitized
diagnostics, and follow [the private security-reporting process](../SECURITY.md).

## Upgrade, rollback, and removal

Back up the trusted policy and finish or discard retained tasks before changing
versions. Upgrade to an explicitly selected beta and rerun the smoke checks:

```console
uv tool upgrade 'warrant-llm==VERSION'
ulg --version
ulg dry-run
ulg sandbox-preflight
```

The packaged policy may select a newer immutable runner digest, but upgrades do
not overwrite the user's policy automatically. Compare the release policy and
adopt a new digest only after reviewing it. Roll back by reinstalling an exact
previous version. Task-state forward/backward compatibility is not guaranteed
during beta, so do not rely on a newer task record after rollback.

```console
uv tool install --force warrant-llm==VERSION
```

Remove the command with `uv tool uninstall warrant-llm`. Configuration
and state remain for recovery. After reviewing exact paths and retained tasks,
use `ulg clean` before uninstalling if those records should also be removed.
