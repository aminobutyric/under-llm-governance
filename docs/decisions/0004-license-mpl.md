# ADR 0004: License the project under MPL-2.0

- Status: accepted
- Date: 2026-08-02

## Context

The project is intended to be shared publicly, but not as unrestricted
permissive code. The user wants a more restricted license than Apache 2.0 while
still keeping the project open source.

## Decision

License the repository under the Mozilla Public License 2.0 (`MPL-2.0`).

## Consequences

When modified covered source files are distributed, they remain under MPL-2.0,
which preserves a file-level share-back obligation. Separate new files in a
larger work can use different licensing terms. MPL does not restrict private
use, internal modification, commercial use, or merely providing a hosted
service. This is consistent with an open-source community core plus separately
licensed enterprise modules. Trademark use remains separate from copyright
licensing. See Mozilla's [MPL 2.0 FAQ][mpl-faq] for practical guidance.

[mpl-faq]: https://www.mozilla.org/en-US/MPL/2.0/FAQ/

## Rejected alternatives

### Apache 2.0

Rejected because it is too permissive for the user's stated preference.

### GPL/AGPL

Rejected because they are stronger copyleft licenses than requested and would
impose broader sharing obligations than the user wants.

### Proprietary or source-available only

Rejected because the user asked for a more restricted license, not a closed
distribution model.
