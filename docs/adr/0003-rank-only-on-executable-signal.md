# ADR-0003: Ranking reads executable signal only; judges inform and never rank

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** Bogdan Dzekic

## Context
SPEC §4 defines four tiers of evidence in descending order of how much they should be trusted:
executable results, cost and latency, diff distance to ground truth, and LLM-as-judge. The report
shows all four and never blends them into one number.

The pressure to blend them is real. A composite score is easier to present, and the judge tier is
the one that can say something about code quality that no test asserts. But a judge is a model
grading a model, on a rubric somebody wrote, and the moment it moves a ranking the harness stops
measuring whether a tool works and starts measuring whether one model likes another's output.
This project's whole claim is that it can tell the difference between an AI feature genuinely
working and merely responding (CLAUDE.md). Ranking on anything a model said would forfeit it.

## Decision
Exactly one function in the codebase decides which tool is ahead: `decide_verdict` in
`src/assay/report/model.py`. It reads one input — the pass^n confidence intervals in two
`ToolSummary` values, which are derived from recorded `Outcome`s and nothing else. Every renderer
prints the `Verdict` it produced through `format_verdict`, so JSON, text and HTML cannot drift
into three claims about one measurement, and no renderer compares two point estimates itself.

`Outcome.NOT_SCORED` exists so that a trial which ran but that no executable signal could rank is
reported as such rather than silently counted as a failure.

This is structural rather than a habit: renderers depend on the report schema and nothing further
up, so what a report does not carry, a renderer cannot show.

No milestone in SPEC §7 schedules judges, so this ADR is a constraint on whichever one first adds
them. When it does: a judge's output enters the report as its own field with inter-judge
agreement beside it, and it does not enter `ToolSummary` or `decide_verdict`.

## Alternatives considered
- **A weighted composite across all four tiers.** Rejected: the weights are an editorial claim
  wearing a number's clothes, and nobody reading the result can audit them. It also lets a strong
  judge score paper over a failing test suite.
- **Let judges break ties when the intervals overlap.** Rejected: it makes the least trustworthy
  signal decisive exactly where the trustworthy one is weakest — the precise inverse of
  [ADR-0005](0005-no-winner-when-intervals-overlap.md), and far more tempting than it looks,
  because a tie feels like a gap the report ought to fill.
- **Rank on diff distance to ground truth.** Rejected: a tool that solves the task differently
  from the human is not wrong (SPEC §4.3). Distance measures agreement with one author's
  approach, which is not the property being bought.
- **Rank on cost, secondarily.** Rejected: cost per solved task is reported, and it is the number
  a buyer wants — but a cheap tool that fails is not ahead of an expensive one that works, and a
  secondary sort key becomes a primary one the moment two tools tie.
- **Drop judges entirely and report only what runs.** Rejected: some criteria genuinely cannot be
  executed, and SPEC §4.4 already constrains them properly (≥3 judges, Krippendorff's alpha
  stated, a same-family judge flagged, the criterion dropped rather than reported weakly if
  agreement is poor). Removing the tier would lose information the report can carry honestly.

## Consequences
A tool that writes elegant unrunnable code scores zero, and the report says why rather than
splitting the difference. A ranking cannot be improved by adding a new signal — only by making
more of the repository's behaviour executable, which is the incentive this project wants.

The cost is that the report will sometimes have nothing to say about a real quality difference
between two tools whose tests both pass. That gap is deliberate and is left visible.

Residual limit worth naming: pass^n is derived from `Outcome`, and at M0 an outcome is carried in
the document rather than computed — there is no scorer until M2 (SPEC §7). Until then this
guarantee is about where a ranking may *read* from, not about the ranking being measured.
