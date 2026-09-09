# v0.1 security acceptance matrix

This matrix binds every release case in the security model to executable test
evidence. A case passes only when its named tests prove containment and produce
or validate a bounded, useful audit event. The five `live Docker` entries must
run against the exact digest-qualified GHCR candidate configured in the release
policy; a normal local test run skips them.

| Case | Threat and containment evidence | Audit evidence | Gate |
|---:|---|---|---|
| 1 | `test_security_case_01_unsafe_model_paths_are_rejected_and_audited` rejects traversal and absolute model paths before tool execution and preserves the source. | `model_failed` followed by a completed retry is asserted. | automated |
| 2 | `test_security_case_02_workspace_symlink_is_contained_and_audited` rejects a post-snapshot link to `/etc/passwd`. | `tool_finished(error_code=unsafe_path)` is asserted. | automated |
| 3 | `test_security_case_03_symlink_swap_is_contained_and_audited` replaces a checked file during descriptor-relative open and returns no bytes. | `tool_finished(error_code=unsafe_path)` is asserted. | automated |
| 4 | `test_security_case_04_special_file_is_contained_and_audited` rejects a FIFO introduced after snapshot creation. | `tool_finished(error_code=unsafe_path)` is asserted. | automated |
| 5 | `test_security_cases_05_and_13_prompt_injection_cannot_reveal_secret` reads a hostile README and then attempts its requested secret read; the secret remains excluded. | The denial is `tool_finished(error_code=excluded_path)` and serialized events contain no secret. | automated |
| 6 | `test_network_host_authority_and_privilege_escalation_are_absent` checks absent curl, DNS, localhost/Ollama connectivity, raw sockets, devices, Docker socket, capabilities, and host marker. | `_assert_auditable` validates a metadata-only `sandbox_finished` event. | live Docker |
| 7 | `test_timeout_output_and_workspace_disk_are_bounded` and `test_process_memory_environment_and_input_are_contained` exercise loops, PID exhaustion, detached children, memory, and disk; the exact detached container is confirmed absent afterward. | Each result is converted to and validated as `sandbox_finished`, including normalized failure codes. | live Docker |
| 8 | `test_timeout_output_and_workspace_disk_are_bounded` triggers stdout flooding and asserts bounded observed/stored output. | `sandbox_finished(error_code=output_limit, output_truncated=true)` is validated without command output. | live Docker |
| 9 | `test_git_hooks_and_package_lifecycle_scripts_are_not_implicitly_executed` places hostile Git and package scripts in the input and runs only the trusted pytest argv; neither marker appears. | A successful metadata-only `sandbox_finished` event is validated. | live Docker |
| 10 | `test_security_case_10_model_cannot_supply_container_authority` rejects model-provided argv, image, mount, and environment fields; `test_runner_command_has_fixed_least_privilege_profile` checks the constructed command. | Invalid authority is recorded as `model_failed`. | automated |
| 11 | `test_replayed_recipe_action_is_rejected_audited_and_reprompted` proves a consumed action cannot execute again; terminal prompt tests exclude model prose and raw patches. | `grant_rejected(reason_code=grant_action_replayed)` and a fresh `approval_requested` are asserted. | automated |
| 12 | `test_run_cli_exports_patch_without_modifying_original` covers successful editing; `test_security_cases_12_and_14_failed_multifile_patch_is_atomic_and_audited` covers failed editing. Both preserve original files. | Success records generation/export/discard; failure records `tool_finished(error_code=patch_rejected)`. | automated |
| 13 | `test_security_cases_05_and_13_prompt_injection_cannot_reveal_secret` and `test_read_only_tools_are_bounded_and_recheck_secret_exclusions` cover snapshot, model-context, tool-result, and audit exclusion. | Serialized audit is explicitly checked for the canary secret and contains only `excluded_path`. | automated |
| 14 | `test_security_cases_12_and_14_failed_multifile_patch_is_atomic_and_audited` makes the second hunk fail after the first could apply; generation zero remains current and no successor is published. | `patch_rejected` exists and `workspace_generation_published` does not. | automated |
| 15 | `test_security_case_15_initial_context_limit_failure_is_audited`, `test_read_only_tools_are_bounded_and_recheck_secret_exclusions`, `test_audit_reader_builds_bounded_redacted_summary`, and the live output-flood test cover context, read/search/list, audit, and command-output budgets. | Context overflow records `task_failed`; other tests assert truncation metadata and bounded audit serialization. | automated + live Docker |

## Release command

```console
uv lock --check
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy src
uv run --frozen pytest
ULG_RUN_DOCKER_TESTS=1 uv run --frozen pytest -q \
  tests/test_sandbox_docker_integration.py
```

The release evidence must record the source commit, configured runner reference,
wheel version, test totals, Docker daemon properties, runner inventories, and
the UTC execution time.
