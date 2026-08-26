# ADR-0002: Tasks are mined from git history, not authored

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** Bogdan Dzekic

## Context
The question Assay exists to answer is "will this tool work on **our** codebase" (SPEC §1) — our
frameworks, our conventions, our fifteen years of history. A hand-written task set cannot answer
it. Whoever writes the tasks decides what counts as hard, and the result measures the author's
model of the repository rather than the repository.

A repository's own history already contains ground-truthed tasks, for free and in the codebase's
own idiom: a merged commit that changes source *and* has tests that went red-to-green (SPEC §3).
The catch is that a commit touching tests is only a *candidate*. Flaky tests, environment drift
and tests that do not actually cover the change all produce candidates that look fine and prove
nothing. So the mining idea is only trustworthy with the red→green gate attached: verify the
tests fail at the parent, verify the ground-truth diff turns them green, discard anything that
cannot demonstrate both, and count the discards.

## Decision
Every task in a suite is derived from a commit and carries exactly what the gate needs to be
re-run by someone else. `Task` (`src/assay/suite/models.py`) records `base_commit` as a full
40-character lowercase SHA-1 — an abbreviated or symbolic ref is not reproducible — and keeps
`test_patch` and `ground_truth_patch` as two separate fields, because the split between them is
the thing the gate depends on. `fail_to_pass` has `min_length=1`: a task with nothing to turn
from red to green has no gate and cannot be scored. There is no author field, and `metadata` is
a `Mapping[str, str]` of provenance a human reads, not a place to smuggle structure in.

At M0 the schema is the *record* of this decision, not its enforcement. The miner and the gate
are M1's whole scope (SPEC §7); enforcing that `test_patch` touches only test files needs the
repository, which no M0 code has. A hand-written document that satisfies the schema loads today,
and the M0 tests write several — deliberately, since a hand-written task round-tripping through
the schema is M0's stated exit criterion.

## Alternatives considered
- **Author a starter task set by hand.** Rejected: it measures the author's assumptions, and it
  is the exact thing a buyer discounts when a vendor brings their own benchmark.
- **Adopt SWE-bench or another public set.** Rejected: contaminated for any repository predating
  a model's training cutoff, and it answers a question nobody in a POC asked (SPEC §2). Assay
  does not compete with those suites; it measures somewhere they cannot reach.
- **Mine without the gate — take every commit that touches tests.** Rejected: this is the
  tempting version, because it yields ten times the tasks. It also yields a number that looks
  like a measurement and is not one. The gate is the entire trustworthiness story.
- **Have a model generate tasks from the repository.** Rejected: circular — a model's output
  becomes the yardstick for models — and a generated task has no ground-truth diff, so there is
  nothing to check the gate against.
- **Let a human repair a candidate that fails the gate.** Rejected: it readmits authored
  assumptions through the back door, and it destroys the yield number by making the denominator
  editable.

## Consequences
Yield becomes a headline rather than an embarrassment: "1,847 commits examined → 213 valid
tasks" is the honest form, and it is more persuasive than the task count alone. A repository with
weak tests yields few tasks, and that is itself a finding about the repository.

Task supply is bounded by history, so a young repository cannot be evaluated well. There is no
workaround inside this decision — the alternative is authoring, which is what it rejects.

Deferred: only test-anchored fixes are mined (M1). Feature-implementation and
refactor-preservation tasks are M5+, and code navigation is v2 (SPEC §3). Each is a different
mining rule over the same history, and none of them relaxes the gate.
