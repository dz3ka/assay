# ADR-0005: Overlapping intervals declare no winner, and the schema refuses to say otherwise

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** Bogdan Dzekic

## Context
"Tool A 61%, Tool B 58%" is a leaderboard. "Tool A 61%, Tool B 58%, not significant at n=213×5"
is a measurement, and SPEC §4 says the second is the stronger signal — it is the thing that makes
an engineer take the harness seriously, and the refusal to name a winner is the most memorable
moment of the demo (SPEC §10).

SPEC §8.5 says this is enforced in the report renderer, not left to the reader. That is the right
instinct and one layer too high. There are three renderers, so "the renderer enforces it" is
three chances to get it right, and the table is what gets screenshotted out of context.

## Decision
The comparison is taken once, in `decide_verdict`, and carried as a `Verdict` model. Overlap is
`a.low <= b.high and b.low <= a.high` — the intervals are closed, so intervals touching at a
single point count as overlapping.

The rule is an invariant of the schema, not a habit of the function that applies it. `Verdict`
validates that `winner` and `reason` agree: a named winner with reason `intervals_overlap` will
not construct, and a null winner with `intervals_disjoint` will not construct either. A report
that names a winner its intervals cannot separate is therefore not a document Assay is able to
build, whatever a future caller does.

The English sentence lives in `format_verdict`, outside the document, because a report's JSON is
API once public (CLAUDE.md) and a headline string in the schema would freeze one wording as a
compatibility promise.

M0 has no Wilson computation, so it ships `stub_interval` — pass^n ±0.25 clamped to [0, 1] — and
the report carries `intervals_are_placeholders`, with all three renderers printing
`STUB_INTERVAL_NOTICE` verbatim while it is true. The suppression path is exercised end to end
from M0 rather than waiting for real statistics.

## Alternatives considered
- **Rank on the point estimates and add a significance footnote.** Rejected: the ranking is what
  travels. A footnote under a sorted table is a disclaimer, not a finding.
- **Enforce it only in the renderers, as SPEC §8.5 literally says.** Rejected: three renderers,
  three opportunities, and a fourth output format later would start from zero. The invariant
  belongs in the type that carries the claim.
- **Treat touching endpoints as disjoint, to break more ties.** Rejected: both estimates are
  consistent with the shared point, so separating tools on a hair's breadth is claiming more than
  was measured — and ties are the outcome this ADR exists to protect.
- **Use a p-value threshold instead of interval overlap.** Rejected: M4 does add a paired
  significance test (SPEC §7), but a threshold is a rule the reader cannot see in the numbers,
  whereas two printed intervals that visibly touch explain themselves.
- **Defer the whole path to M4, when real intervals exist.** Rejected: a code path first written
  in the milestone that also introduces the arithmetic is a path whose first test is written
  against numbers nobody has checked yet. Stubbing the interval and testing the refusal now is
  the cheaper order, and it is what KICKOFF item 6 asks for.

## Consequences
A report may name no winner at all, and that is a successful run, not an inconclusive one.

A follow-up is now pinned: when M4's Wilson intervals land, `stub_interval`, `_STUB_HALF_WIDTH`
and `STUB_INTERVAL_NOTICE` must be deleted in the same change. A measured interval still
captioned "placeholder" lies in the other direction, and the renderer tests assert the notice
verbatim — they are the tripwire that fires if it outlives the stub.

Residual: overlap is judged on pass^n only. Two tools could separate on pass@1 and still be
reported as no winner. That is deliberate — pass^n is the number the decision is about
([ADR-0004](0004-pass-caret-n-is-the-headline-metric.md)) — but it is a real loss of resolution
and should not be discovered later as a surprise.
