# ADR-0012: The mined-task-id pattern is spelled twice, and a drift test licenses it

- **Status:** Accepted
- **Date:** 2026-08-27
- **Deciders:** Bogdan Dzekic

## Context
`^[a-z0-9][a-z0-9._-]{0,127}$` — the shape of a mined task's id — appears in two files:
[`suite/models.py:22`](../../src/assay/suite/models.py), where a `Task` declares what the miner
may mint, and [`results/models.py:51`](../../src/assay/results/models.py), where a `Result` and an
`Attempt` declare what they may cite. The two spellings are byte-identical, which reads as an
omission somebody should tidy.

It is not one, and the reason is a dependency direction rather than an aesthetic. `assay.results`
imports nothing from `assay.suite` and `assay.report` imports nothing from it either — the only
shared ancestor is `assay.core`. That is deliberate: a result set is a document read by callers
that never load a suite. `assay report` renders results a different machine produced, from a
suite that may not be on disk at all, and the constraint a `Result` enforces on itself must not
depend on a package it has no reason to import.

So the duplication buys package independence, and the cost is drift: two patterns that must stay
identical with nothing making them so.

## Decision
Keep both spellings, and pin them against each other with a test rather than a shared symbol:
`test_the_results_task_id_pattern_is_the_suite_schemas_pattern`
(`tests/results/test_models.py:406`) asserts the two module-level constants are equal. Widen one
and the suite fails until the other follows.

The test is the licence for the duplication. It is not incidental coverage, and it is not
redundant with the per-field shape tests around it — those check that each schema rejects a bad
id, which both would continue to do while drifting apart.

## Alternatives considered
- **Import the pattern across packages** (`from assay.suite.models import _TASK_ID_PATTERN`).
  Rejected: it makes reading a result set depend on the suite package, which is the coupling the
  layering exists to prevent, and it does so for one string constant.
- **Hoist the pattern into `assay.core`.** The honest runner-up: `core` is already the shared
  ancestor and already exports cross-cutting primitives (`HASH_PREFIX`, `SchemaKind`,
  `SchemaModel`). Rejected for M0 because the two constraints are *coincidentally* identical, not
  identically *defined* — the suite's pattern says what the miner may mint, the results' says what
  a recorded trial may cite, and M1's miner is where the first could legitimately narrow while the
  second stays wide to keep old result sets readable. A shared constant would make that divergence
  a refactor rather than an edit. If M1 confirms the two are one concept, hoisting is a small
  change and this ADR is the one it supersedes.
- **Leave the duplication undefended and rely on review.** Rejected: the drift is invisible in a
  diff that touches one file, which is exactly the diff that causes it.

## Consequences
Widening the mined-id shape is a two-file edit with a test that names the second file for you.
Deleting the drift test re-opens the hole silently, so it is named here as the thing holding the
duplication closed rather than as one more test in a file of them.

Anyone reading either module sees a constant that looks unshared and may "fix" it by importing
across packages. The comment at each site and this record are the only defences against that,
since a passing suite would not object — the equality test is satisfied by a shared symbol just
as well as by two equal ones. Reviewers should read a cross-package import of this constant as a
regression against [ADR-0011](0011-string-constraints-live-on-the-schema.md)'s layering, not as
cleanup.
