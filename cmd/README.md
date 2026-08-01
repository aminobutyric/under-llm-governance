# Command entry points

Phase 0 will add `cmd/ulg`, the local command-line interface. Entry points must
contain only process setup and dependency wiring; security logic belongs in
testable packages under `internal`.

Planned commands are introduced with the phase that can implement them safely:

- Phase 1: `ulg inspect`
- Phase 2: `ulg diff` and `ulg export-patch`
- Phase 4: `ulg run`, `ulg resume`, `ulg promote`, `ulg audit`, and `ulg clean`
