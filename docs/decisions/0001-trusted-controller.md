# ADR 0001: Keep the model outside the authority boundary

- Status: accepted
- Date: 2026-08-01

## Context

A coding model must inspect files, propose edits, and request verification. A
naive implementation gives the model a shell in the user's project and relies
on prompts to constrain behavior. Model output can be wrong or manipulated by
instructions embedded in repository content, so prompt-level constraints cannot
protect the host.

## Decision

Run a trusted controller as the sole owner of capabilities. The model receives
schemas describing narrow tools and proposes calls. The controller parses,
normalizes, authorizes, audits, and executes accepted calls. Command execution
occurs in a separate disposable sandbox. The model service and task sandbox do
not receive direct references to each other.

The following data is always untrusted at the controller boundary:

- model responses;
- repository contents and names;
- tool and command output;
- configuration stored inside a selected project.

## Consequences

Benefits:

- Permission enforcement remains effective even if the model ignores its
  instructions.
- Policy can be unit-tested without calling a model.
- Ollama can be replaced without redesigning tools or authorization.
- Audit records can distinguish proposed actions from executed actions.

Costs:

- Every useful operation needs a typed tool and validator.
- The controller and sandbox launcher become security-critical code.
- Some flexible coding workflows will arrive later than they would with an
  unrestricted shell.

## Rejected alternatives

### Give the model a host shell

Rejected because the shell inherits ambient filesystem, process, environment,
credential, and network authority from the host user.

### Rely on system-prompt prohibitions

Rejected because prompts guide model behavior but cannot enforce operating
system permissions or withstand all indirect prompt injection.

### Put the complete controller inside the task container

Rejected for the initial design because task code would then share a network and
process boundary with the model client and approval logic. Keeping those
components outside reduces the authority available to compromised project code.
