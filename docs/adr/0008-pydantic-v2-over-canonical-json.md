# ADR-0008: Data contracts are pydantic v2 models over canonical JSON, addressed with SHA-256

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** Bogdan Dzekic

## Context
Every document Assay reads or writes is a contract with someone: a suite file with a future run,
a result set with a report, a report with a vendor. Two properties are needed at once.

First, a document that is not what it claims must be refused loudly at the boundary. The
dangerous case is not a typo — it is a suite written by a *future* Assay version loading in an
older build with the fields it does not know about silently dropped. A dropped field changes the
content hash, and a changed hash with no error attributes a result to the wrong task set, which
defeats [ADR-0007](0007-suites-are-content-addressed-and-versioned.md) outright.

Second, the bytes have to be stable. Two structurally equal values must encode identically on
every platform and every run, or the address is not an address.

And CLAUDE.md requires full annotations under `mypy --strict` with no bare `Any`, so the runtime
shape and the static type have to be one declaration, not two that drift.

## Decision
pydantic v2, and it is the project's only runtime dependency. One base class, `SchemaModel` in
`src/assay/core/model.py`, sets `extra="forbid"` and `frozen=True` for every schema in the
project — which is what makes those two properties structural rather than a rule each new model's
author has to remember.

Canonical bytes come from `assay.core.canonical`: sorted keys, no whitespace, UTF-8, and floats
refused anywhere in the structure with the JSON path to the offender named in the error.
`content_hash` is `sha256:` plus the hex digest over exactly those bytes.

## Alternatives considered
- **stdlib `dataclasses` plus `TypedDict`.** Rejected, and this is the decisive comparison:
  neither rejects an unknown field at runtime. A `TypedDict` is a static fiction that a
  `json.loads` result is asserted into, so the future-suite case above loads clean and wrong.
  Zero dependencies is a real prize and it is not worth that.
- **`msgspec`.** Rejected: it is faster, and no performance requirement exists. An eval run is
  dominated by container start-up and model latency, so a faster validator saves nothing
  measurable while costing a less widely known dependency at the project's contract boundary.
- **`attrs` plus `cattrs`.** Rejected: two dependencies to do one job, and the
  validation/serialisation split would put the `extra="forbid"` decision into converter
  configuration rather than into a base class anyone can read in ten lines.
- **JSON Schema files plus a generic validator.** Rejected: the schema and the Python type become
  two artefacts kept in sync by hand — the exact drift `mypy --strict` was adopted to prevent.

## Consequences
**The standing risk against this choice did not materialise.** The argument against pydantic was
its history of friction under `mypy --strict`. In this tree `mypy --strict` passes over `src` and
`tests` with no pydantic mypy plugin configured, and there is no `# type: ignore` anywhere in
`src`; the two in `tests` are deliberate static-negative assertions, and `warn_unused_ignores`
makes a stale one fail CI. Recorded plainly so the risk is not re-litigated from memory.

`SchemaModel` is the mechanism, not a convenience: a new schema inherits both properties, and a
model wanting a different stance has to say so visibly, in a diff a reviewer will see.

`frozen=True` means documents are rebuilt rather than edited — a hashed document that could be
mutated afterwards would have a digest describing something else. `redact` returns a new `Report`
and names every field, so a field added in a later milestone fails to compile there first.

Refusing floats at the canonical boundary has two downstream effects worth naming: money must be
a `Decimal` ([ADR-0010](0010-money-is-a-decimal-at-six-decimal-places.md)), and a report — whose
intervals are genuinely floats — is a rendered document rather than a hashed one.
