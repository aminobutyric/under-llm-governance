# MVP readiness checklist

This checklist tracks the shortest secure path from the current Phase 4 work to
a user-friendly, end-to-end MVP. Check an item only when its implementation,
negative tests, documentation, and relevant acceptance evidence are complete.

## 1. Interactive approval bridge

- [x] Define strict controller-owned approval request and response models.
- [x] Summarize approval-sensitive patches from parsed paths and operations.
- [x] Show recipe name, trusted argv, sandbox limits, expiry, and use count.
- [x] Render terminal prompts without trusting model rationale or raw patch text.
- [x] Let users deny, approve one exact action, or approve a bounded recipe grant.
- [x] Fail closed on invalid input, EOF, or unavailable approval services.
- [x] Audit approval requests, decisions, grant issuance, consumption, and rejection.
- [x] Advertise `run_task` to the model only in the approval-capable coding workflow.
- [x] Add controller and CLI tests for approval, denial, reuse, and prompt integrity.

## 2. Durable task lifecycle

- [x] Define explicit plan, execute, review, retry, cancel, export, and discard states.
- [x] Persist task metadata and complete workspace-generation references atomically.
- [x] Persist grants, consumed action identifiers, expiry, and remaining uses safely.
- [x] Make grant consumption and effect scheduling crash-safe and replay-resistant.
- [x] Add `ulg resume TASK_ID` without repeating completed effectful actions.
- [x] Preserve bounded recovery export while making retention an explicit state.
- [x] Add restart, partial-write, stale-config, and concurrent-resume tests.

## 3. Review and operations UX

- [x] Add `ulg diff TASK_ID` for bounded pending-change review.
- [x] Add `ulg audit TASK_ID` with a concise, redacted lifecycle view.
- [x] Add `ulg clean` with explicit targets, age/size reporting, and safe confirmation.
- [x] Make `ulg run` print the task identifier and actionable next commands.
- [x] Produce a final report separating proposals, approvals, executions, verified
      checks, pending changes, failures, and model-authored summary text.
- [x] Improve errors for unavailable Ollama, Docker preflight failure, and expiry.

## 4. MVP security acceptance

- [x] Map every adversarial case in `docs/security-model.md` to an automated test.
- [x] Assert both containment and useful audit evidence in every adversarial test.
- [x] Complete prompt-injection, misleading-approval, lifecycle-script, and Git-hook
      scenarios.
- [x] Rerun all live rootless-Docker acceptance groups on the release candidate.
- [x] Verify interruption and restart cannot repeat an effectful action.
- [x] Confirm no controller, model, or sandbox path can modify the original project.

## 5. Release readiness

- [x] Refresh README and source-layout documentation for the approval increment.
- [ ] Add the dependency-security check required by the development plan to CI.
- [x] Test installation and the quick start on clean Python 3.11 and 3.13 systems.
- [ ] Document operator setup, state retention, cleanup, recovery, and limitations.
- [x] Record the runner image digest, inventories, and complete acceptance evidence.
- [x] Mark the MVP complete only after Phases 0-4 and all security gates pass.
