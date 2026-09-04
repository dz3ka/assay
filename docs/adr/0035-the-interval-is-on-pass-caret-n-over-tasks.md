# ADR-0035: The interval is Wilson over tasks, and pass@1 is printed with an explicit no-interval marker

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0034](0034-wilson-lands-in-m3-and-the-placeholder-is-deleted.md) brings the real interval
forward into M3. That settles the arithmetic and immediately raises the two questions the
arithmetic cannot answer: what the denominator is, and what happens to the number that has no
honest band at all.

A report shows two scores per tool. pass^n is the fraction of tasks on which *every* trial
passed — the enterprise number, and the one a comparison is decided on
([ADR-0004](0004-pass-caret-n-is-the-headline-metric.md)). pass@1 is the mean over tasks of
each task's own pass rate, and `summarise` computes it that way deliberately: pooling every
trial into one ratio would let a task that happened to be run more often carry more of the
score, so two tools with different trial counts would be scored on differently weighted task
sets while appearing to share a metric.

The denominator question has a tempting wrong answer sitting right next to the right one.
`ToolSummary` carries a `trials` field, it is the larger number, and a larger denominator makes
a narrower band. It is also already on the object being built, so `wilson_interval(successes,
summary.trials)` reads as the obvious call. It would be wrong in the direction that flatters:
running the same five tasks five times each instead of once would report a band tightened by a
factor it did not earn, because rerunning a task is not a new observation of whether a tool can
solve a *different* task.

pass@1 has no such answer. It is a mean of per-task rates, not a count of successes over a count
of trials, so there is no binomial proportion for Wilson to be an interval *of*. Its honest
uncertainty is a bootstrap over tasks, which SPEC §7 puts in M4 along with the paired
significance test. So M3's report shows one score with a band and one score without, and a
column printed without a band beside a column printed with one reads as the *more* certain of
the two.

## Decision
**The interval is a Wilson band on pass^n whose denominator is the number of tasks, and pass@1
is printed with an explicit marker saying it has no interval and why.** `summarise` calls
`wilson_interval(successes=fully_passed, trials=len(outcomes_by_task))` — both arguments are
task counts. The trial count stays on the summary as evidence of how much work stands behind
the score, and nothing computes a band from it.

The band is on pass^n and not on pass@1 because pass^n is the only one of the two that is a
binomial proportion. Each task is one Bernoulli observation: either every trial of it passed or
not. That is exactly the shape Wilson is an interval for, and it is also the number the
no-winner rule compares ([ADR-0005](0005-no-winner-when-intervals-overlap.md)), so the rule and
the arithmetic are about the same quantity.

The marker is a render-local constant in both prose formats: the text report carries it on the
Tools heading, the HTML page as the caption of the tools table, and the canonical JSON carries
neither the marker nor a band, because prose inside the document would freeze one wording as a
compatibility promise. It names the reason rather than stating an absence — a bootstrap over
tasks, landing in M4 — because "no interval available" reads as a gap in the tooling, and this
is a statement about the shape of the number.

A silent omission was offered and rejected by the user. Nothing in the rendered report would
have been false; it would simply not have said that the missing band was a decision. For a
project whose subject is measurement honesty, an unexplained blank is the reader's problem to
solve, and they will solve it by assuming pass@1 is the surer number.

## Alternatives considered
- **Use `ToolSummary.trials` as the denominator.** Rejected, and it is the mistake this record
  exists to prevent: it is the shorter expression, the field is already in scope, and the
  reported band comes out narrower. It answers a different question — "of all trials run, what
  fraction were in tasks that fully passed" — with a denominator that grows by rerunning the
  same task. Confidence bought by repetition of the same observation is the cheapest way to
  fake it in this whole codebase.
- **Pool pass@1 into a proportion — passing trials over all trials — so Wilson applies to it
  too.** Rejected. It would put two definitions of pass@1 in one report: the mean-over-tasks
  figure in the column, and the pooled ratio the interval was computed from. A reader who
  checked the band against the number beside it would find they disagree, and the fix for that
  is to change what pass@1 means, which is a metric decision SPEC §4 already took the other
  way.
- **Bootstrap pass@1's interval now, in M3.** Rejected on scope, not on correctness — it is the
  right answer and SPEC §7 schedules it for M4 next to the paired significance test, where it
  belongs with the other resampling work. Pulling one interval forward would mean writing the
  resampling seam twice, and M3's ranking does not read pass@1.
- **Print pass@1 with no band and no comment.** Rejected by the user, explicitly. The omission
  is stated, never silent.
- **Drop pass@1 from the report until it has an interval.** Rejected. SPEC §4 requires both
  numbers, and pass@1 is what makes pass^n legible: a tool at pass@1 0.8 and pass^n 0.2 is
  unreliable, while one at 0.25 and 0.2 is simply weak, and those are different findings.

## Consequences
The band is honest about how little evidence a small suite carries, and the first thing that
showed was inside the test fixtures. The oracle bracket — a tool that passes everything against
one that fails everything — does not separate at two tasks: 2/2 gives [0.342, 1] and 0/2 gives
[0, 0.658], which overlap, so the report declares no winner even for a perfect tool. Separation
needs the task count to exceed z² ≈ 3.84, so five tasks in the fixture. That is the harness
working: the M0 placeholder band declared a winner on two tasks, and it should not have.

pass^n's interval will look wide in M3's milestone record, because the fixture repository yields
two tasks and a real mined suite yields a few hundred. A reader who takes that width as a defect
of the method has it backwards, and the milestone record says so rather than leaving the number
to speak for itself.

The report now shows one score with a band and one without, in every format, permanently until
M4 lands the bootstrap. The marker is the thing that keeps that asymmetry from reading as a
claim, and it is asserted verbatim in the renderer tests — the same tripwire arrangement
ADR-0005 used for the placeholder notice, for the same reason: when M4 gives pass@1 a real
interval, the marker must die in that change.

`summarise` stays the only function that decides what a success is. `assay.stats` is handed two
integers and never learns they were tasks, which is what lets its own tests be pure arithmetic
against hand-computed values, and what keeps this decision reviewable in one function rather
than spread across a package.
