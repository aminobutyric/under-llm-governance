# Milestone 5: beta adoption

Objective: five independent developers install Warrant and attempt a real coding
task. Record feedback manually and with participant consent; no telemetry is added.

- [x] Reconcile release and MVP checklists with the published beta evidence.
- [x] Add a public beta feedback issue form.
- [x] Write the [first-task tutorial](first-task.md).
- [x] Implement `ulg doctor` and test failure reporting.
- [ ] Have a new user follow the tutorial on a supported machine; record friction.
- [ ] Record a short demo of inspection, patch review, and approved test execution.
- [ ] Publish the onboarding changes in a new beta following the release procedure.
- [ ] Update the landing page in its separate repository with install and tutorial links.
- [ ] Publish the announcement below and invite 5–10 Linux/Ollama users.
- [ ] Review feedback and prioritize observed installation and workflow problems.

Suggested adoption targets: five installs, four successful initializations, three
completed inspect/edit/test tasks, and two voluntary repeat users. These are
planning targets, not measured results. Record setup/task time, help required,
approval clarity, original-file integrity, and whether the user returned.
Track security reports privately and resolve critical issues before widening use.

## Announcement draft

Warrant's public beta is available as `warrant-llm` on PyPI. It lets a local
Ollama coding model inspect and edit disposable copies of a project, run approved
checks in an offline rootless Docker sandbox, and export a patch for human review.
The original project remains unchanged by the agent workflow.

We're looking for Linux amd64 developers who already use Ollama to try one small
task and share what worked and where setup was confusing. This beta supports one
local user/task at a time and does not install project dependencies or apply
patches automatically. It collects no usage telemetry.

Install: `uv tool install warrant-llm==0.1.0b3` (update this pin when the next beta
is published). Start with the first-task tutorial linked from the repository README.
Feedback and support: https://github.com/aminobutyric/warrant/issues
Private security reports: https://github.com/aminobutyric/warrant/security/advisories/new

This is a draft; publication and outreach remain separate tasks.
