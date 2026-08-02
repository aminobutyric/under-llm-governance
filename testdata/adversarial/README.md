# Adversarial fixtures

This directory will contain inert test fixtures that exercise the security
boundaries. Fixtures must never contain real secrets or automatically execute
on a developer machine.

Planned fixture groups:

- path traversal and absolute paths;
- symlink and path-replacement races;
- special files and `/proc`-style magic links;
- prompt injection in source, documentation, filenames, and tool output;
- malicious Git hooks and repository configuration;
- network and localhost connection attempts;
- fork, memory, disk, and output exhaustion;
- package lifecycle scripts;
- approval replay and misleading descriptions;
- attempts by the controller or sandbox to modify the original source.

Every fixture needs an expected denial or containment result and an expected
audit event. Tests should invoke fixtures only inside the sandbox designed for
that test.
