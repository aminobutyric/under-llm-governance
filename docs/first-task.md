# Your first Warrant task

Allow about ten minutes for this exercise **after** installing prerequisites and
downloading the model and runner. Model speed depends on your hardware; this is
not a completion-time guarantee. Use Linux amd64, Python 3.11–3.13, uv, local
Ollama, and rootless Docker with cgroup v2/systemd. See [operations](operations.md).
The default model is `qwen3-coder:30b`; confirm it runs comfortably on your machine
before starting. Downloads and model memory requirements are additional to the
sandbox's memory limit.

## Install and check setup

The published beta is installed with:

```console
uv tool install warrant-llm==0.1.0b3
ulg init
ollama pull qwen3-coder:30b
ulg dry-run
ulg sandbox-preflight
```

`ulg doctor` is added in the next release. To try it from this checkout, run
`uv sync --frozen` then `uv run ulg doctor`. It checks the configured model and
runner as well as Docker. Follow the printed fixes, including pulling the exact
runner digest, then rerun it. `uv run ulg doctor --json` prints structured results.
The command does not download anything or run inference. A passing result checks
setup, not model quality or whether a particular project's tests will pass.

For the published beta, pull the digest recorded in your policy following the
[runner setup instructions](../README.md#offline-sandbox-setup).

If you already have a policy, keep it; `ulg init` refuses to overwrite it. Select
another installed model with `--model NAME` on the commands below if needed.

## Create a tiny project

Create a new directory outside the Warrant checkout, with these two files.
It uses only Python and pytest, already included in the accepted runner.

`greeting.py`:

```python
def greet(name):
    return f"Hello, {name}!"
```

`test_greeting.py`:

```python
from greeting import greet


def test_greet():
    assert greet("Ada") == "Hello, Ada!"
```

Replace `/absolute/path/to/hello-warrant` below with this directory's path.

## Inspect, change, and verify

```console
ulg inspect --workspace /absolute/path/to/hello-warrant \
  --task "Explain the greeting function and its test. Cite the files you read."
ulg run --workspace /absolute/path/to/hello-warrant \
  --task "Strip surrounding whitespace from the name in greet. Add a test for this while preserving the existing test. Run the test recipe, inspect the diff, and finish." \
  --output /absolute/path/to/greeting-change.patch
```

Choose a new output path outside the example directory. When Warrant asks to
run the `test` recipe, review the fixed command and sandbox limits, then approve
one execution. Expect the original test and the new whitespace test to pass.
Check the final report for actual execution results; the model's summary alone
is not verification. The original two files should still be unchanged.

Open the exported patch in your editor and review both the function change and
the new test. Applying it to your original files is a separate manual decision.
If a task fails or you interrupt it, use the printed task ID:

```console
ulg diff TASK_ID
ulg audit TASK_ID
ulg resume TASK_ID
```

Use `ulg discard TASK_ID` if you want to abandon that retained task. Avoid
rerunning the entire task while a useful resumable generation is available.

## Share what happened

Submit [beta feedback](https://github.com/aminobutyric/warrant/issues/new?template=beta_feedback.yml)
with setup time, where you needed help, whether the task succeeded, and whether
you would try a second task. Review and sanitize anything you include. Warrant
does not send usage telemetry or automatically upload diagnostics.
