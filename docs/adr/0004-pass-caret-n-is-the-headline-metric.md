# ADR-0004: pass^n is the headline metric; pass@1 is reported for comparability

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** Bogdan Dzekic

## Context
These systems are nondeterministic, so a single trial per task measures luck as much as skill.
SPEC §4 fixes n trials per task per tool, default 5, and then has to say which number the report
leads on.

The conventional answer is pass@1, or worse pass@k, which counts a task as solved if any of k
attempts succeeded. pass@k rewards retrying: it goes up with k, and it describes a workflow where
a human re-rolls until something passes. That is not what an enterprise is buying. A buyer
rolling a tool out to 300 engineers does not care that it works one time in five — they care
whether the same prompt gives the same answer on Tuesday as it did on Monday. Reliability is the
purchase, and no public leaderboard puts it on the front page.

## Decision
Both numbers are computed and both are stored, on `ToolSummary` in `src/assay/report/model.py`.

- **pass^n** is the fraction of the tool's tasks where *all* of that task's trials passed.
- **pass@1** is the mean over tasks of that task's own pass rate — not the pooled ratio of
  passing trials to trials. Pooling would let a task that happened to be run more often carry
  more of the score, so two tools with different trial counts would be compared on differently
  weighted task sets while appearing to share a metric.

pass^n is the headline in the sense that decides things: it is the only one carrying a
confidence interval, and it is the number `decide_verdict` compares. `trials` is carried in the
summary next to both, so a reader can see how little or how much the numbers rest on.

`errored` and `not_scored` trials stay in the denominator and are not passes. Excluding harness
failures would flatter whichever tool crashes most.

## Alternatives considered
- **pass@1 alone.** Rejected: it is comparable and conventional and it answers the wrong
  question — a tool at 60% pass@1 might be reliable on 60% of tasks or unreliable on all of them,
  and those are different products.
- **pass@k, best-of-k.** Rejected: it improves as n rises, so the headline number would be tunable
  by whoever ran the eval. It measures the value of retrying, which the buyer is not procuring.
- **pass^n alone, dropping pass@1.** Rejected: comparability is cheap, and refusing to publish
  the conventional number reads as hiding a worse one. Carrying both costs one column.
- **Pool trials rather than averaging per task for pass@1.** Rejected: unequal trial counts across
  tasks silently reweight the task set, which is a statistical error hidden inside a familiar
  metric — the worst kind.
- **A mean success rate with a standard deviation.** Rejected: it describes the spread of a
  distribution, where the decision needs a threshold — "every one of five trials passed" is what
  a rollout depends on, and a standard deviation does not say it.

## Consequences
pass^n falls as n rises, and it should. A tool's headline number therefore depends on the trial
budget, which is why `trials` is on the summary and in every rendered row.

Cost per solved task (SPEC §4.2) has a denominator question this ADR settles by implication:
"solved" is pass^n, not pass@1, so the cost figure is the cost of dependable work.

Worth naming so it is not mistaken for a ranking claim: the per-tool row in all three renderers
prints pass@1 before pass^n, because that is the column order a reader coming from a public
leaderboard expects. Precedence is expressed where it matters — the verdict sentence, the only
ranking claim a report ever makes, is about pass^n.

Deferred: the interval around pass^n is an M0 placeholder, not a Wilson interval. M4 builds the
real one (SPEC §7), and it lands on pass^n because that is the number a comparison is decided on.
