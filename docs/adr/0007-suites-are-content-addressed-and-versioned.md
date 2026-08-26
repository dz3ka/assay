# ADR-0007: Suites are content-addressed and versioned, and a result cites the digest it was measured on

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** Bogdan Dzekic

## Context
A harness that measures the same tools twice will eventually show a number moving, and the only
useful question about that movement is whether the *tool* changed or the *task set* did. Mining
is not stable across time: re-running the miner after a repository gains history, or after the
miner itself is improved, produces a different suite that carries the same name. Without an
identity for the task set, every regression is ambiguous, and SPEC §5.5 and §8.7 both ask for
reproducibility and attribution rather than a version label.

## Decision
A suite file is an envelope around a hashed body. `SuiteBody` holds `schema_version`,
`suite_name` and the tasks, and is the part that is hashed; `SuiteFile` carries `suite_hash`
alongside `generated_at` and `generator`, which sit *outside* the digest, because a digest
covering the clock would give two identical task sets two different addresses and destroy the
property it exists to provide. The address is `sha256:` plus 64 lowercase hex over canonical JSON
([ADR-0008](0008-pydantic-v2-over-canonical-json.md)).

The digest is then carried forward: `ResultSet.suite_hash` names the task set a run was measured
against, and `Report.suite_hash` puts it on the page. A regression between two runs is a tool
change only if that digest stayed the same.

Three supporting refusals close the places the property would otherwise leak:

- Task order is part of the address. `SuiteBody` requires tasks sorted by `task_id` and refuses
  duplicates, rather than sorting them itself — sorting on load would let two different files
  produce one digest.
- `load_suite` probes the version, parses, then recomputes the digest from the parsed value and
  raises `SuiteHashMismatchError` on disagreement. Verifying last means a file edited after it
  was written is refused rather than trusted.
- `schema_version` appears both on the envelope and inside the body. The envelope's is what is
  probed before anything is parsed, so an unreadable version is one sentence rather than a
  parser's field-by-field complaint; the body's is inside the digest, so a hash always states
  which schema it was computed under.

## Alternatives considered
- **A version tag or semantic version on the suite name.** Rejected: a name can be reused, and
  the failure mode is silent. A digest cannot be edited into agreement with the wrong bytes.
- **Hash the whole file, `generated_at` and `generator` included.** Rejected: re-mining an
  unchanged repository would produce a new address every time, so the digest would track when
  mining ran instead of what was mined.
- **Sort the tasks on load and hash the sorted form.** Rejected: convenient, and it makes two
  genuinely different files share an address — the one thing content addressing must not allow.
- **Identify the suite by a git tag in the repository under evaluation.** Rejected: it couples
  the suite's identity to a repository that is not Assay's, is often private, and can be
  force-pushed. The suite is generated from that history, not stored in it.
- **Skip the version field and infer the shape.** Rejected: a document from a future build would
  then be read as an old one with fields missing, which is exactly the silent-drop failure
  [ADR-0008](0008-pydantic-v2-over-canonical-json.md) refuses.

## Consequences
Improving the miner produces a new suite hash and therefore an incomparable result set. That is
correct and it will feel like churn — the cost of being able to say which of the two things moved.

A result set does not verify its own bytes. It cites a suite hash, and checking that citation
means loading the suite, which is a different file. `read_result_set` deliberately has no third
step for this.

Deferred: nothing at M0 refuses to render a report for a result set whose suite it has never
seen — the reporter takes `suite_hash` on trust, because M0 has no run path to check it at. The
milestone that runs a suite (M3, SPEC §7) is where that check belongs.
