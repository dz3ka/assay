# ADR-0044: The paired test is exact McNemar on pass^n, and a significant p never names a winner

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Bogdan Dzekic

## Context
SPEC §4 asks for a paired significance test between tools, and SPEC §7 puts it in M4. The report
already carries the unpaired half: each tool's pass^n gets a Wilson band over tasks
([ADR-0035](0035-the-interval-is-on-pass-caret-n-over-tasks.md)), and
[ADR-0005](0005-no-winner-when-intervals-overlap.md) refuses to name a winner when two of those
bands touch. What is missing is the comparison those two bands are not, and cannot be made into.

Two independent intervals read a paired experiment as if it were an unpaired one. The tools were
not run on separate suites: they were run on the same tasks, from the same content-addressed
digest ([ADR-0007](0007-suites-are-content-addressed-and-versioned.md)), and most of those tasks
say nothing about the difference between them. A task both tools solved and a task neither solved
are noise the two marginal rates carry in full. What is left — the tasks exactly one tool solved —
is the entire evidence about which is better, and no arrangement of the two marginals recovers it.

That matters most in this repository's actual regime. A mined suite is tens of tasks, not
thousands, so the bands are wide and almost always overlap; ADR-0035 found the oracle bracket
failing to separate at two tasks. Two tools can nonetheless disagree systematically on the tasks
they share, and today Assay has no way to say so. It prints two overlapping bands and stops.

The discordant counts are small for the same reason. Across every suite mined to date, `b + c` —
tasks only one tool solved — is under 25, which is precisely the range where the textbook
chi-square McNemar statistic is not valid, and where an exact sum over a binomial with a handful
of terms is not merely affordable but hand-checkable.

The other half of the problem is not arithmetic. A p-value printed beside "No winner: the
intervals overlap" is a number that invites a second reading of the same comparison, and a reader
looking for a winner will find one there. That has to be settled here, in the record, rather than
discovered later by whoever writes the renderer.

Finally, "solved" is not yet a single thing. The report prints pass^n and pass@1, and a paired
test needs one per-task Bernoulli outcome to pair on.

## Decision
**The paired test is the exact two-sided binomial McNemar over discordant tasks. It is taken at
pass^n. Its p is reported beside the verdict and never moves the ranking.** Three decisions, one
record, because separating them would leave two of them looking optional.

**The arithmetic.** `stats/mcnemar.py` adds one function, `mcnemar_exact_p(only_a, only_b)`. Over
`n = only_a + only_b` discordant tasks with `m = min(only_a, only_b)`:

```
p = min(1, 2 * sum(comb(n, i) for i in range(m + 1)) / 2**n)
```

Under the null hypothesis that the tools are the same, each discordant task was as likely to fall
either way, so the split is Binomial(n, 1/2) and the sum is exact — `math.comb`, integer
arithmetic, one correctly rounded division at the end. The doubling is the second tail rather than
a correction: the outcomes at least as lopsided as the observed one are `{X <= m}` together with
`{X >= n - m}`, which are disjoint unless `m >= n - m`. That happens exactly when the split is
even, where the union is every outcome there is and the honest p is 1. `min` states that; it is
the same case that gives `b = c = 0` — the tools solved the same tasks — a p of 1.0.

The function takes two integers and returns a float. No alpha, no threshold, no `significant:
bool`, and no defaults of any kind, following the rule `stats/__init__.py` already states and
[ADR-0043](0043-pass-at-1-is-a-percentile-bootstrap-over-tasks.md) applied to the bootstrap's
seed: a leaf that imports nothing from Assay has no standing to decide what a p means. There is no
new dependency; pydantic remains the only runtime one.

**The pairing is on pass^n.** A task counts for a tool when every one of its `n` trials passed —
the quantity [ADR-0004](0004-pass-caret-n-is-the-headline-metric.md) ranks on and ADR-0035 bands.
So the paired test, the Wilson interval and (in the next package) the cost denominator all
describe one definition of success, and the report does not acquire a third.

**The p never moves the ranking.** `Verdict` keeps exactly two reasons and `decide_verdict` is
untouched. A significant McNemar p sitting beside overlapping Wilson bands is a real and printable
finding — *the tools differ on the tasks they share, and neither tool's own rate is pinned down
well enough to rank them* — and it is not a licence to name a winner. Letting the more permissive
of two statistics unlock the winner claim is ADR-0005's failure mode with one extra step: the
harness would have become the thing it exists to detect, choosing the reading that separates.
**Any future change here supersedes ADR-0005 explicitly.**

The test is computed unconditionally, whether or not the intervals separate. Making the report's
contents depend on its own verdict would mean a reader could infer the verdict from which sections
exist, and SPEC §4 asks for the paired comparison without qualification.

## Alternatives considered
- **Chi-square McNemar with the continuity correction**, the form every textbook prints. Rejected
  twice over. It needs an incomplete-gamma CDF to turn the statistic into a p — some thirty lines
  of numerics checkable only against another implementation, in a repository that spells `Z_95` as
  a literal rather than take a distribution as a dependency for one constant. And it is an
  asymptotic approximation, invalid below roughly 25 discordant pairs, which is every suite this
  harness has mined. It would be the wrong answer computed the expensive way.
- **The mid-p McNemar variant.** A defensible correction for the exact test's conservatism, and it
  would report a smaller p on the same data. Rejected because that is the direction this project
  never picks: where two readings are available, Assay takes the one that does not flatter the
  tool under test. A conservative p that occasionally fails to call a real difference costs less
  here than one that occasionally calls a difference that is not there.
- **Reuse M4's bootstrap as a paired bootstrap over per-task differences.** One seam instead of
  two, and no second module. Rejected on two counts: it makes the significance claim a function of
  a seed, which ADR-0043 accepted for a band only because a band is not a decision; and it cannot
  be checked against a hand-computed value, only against itself, which CLAUDE.md's rule about
  statistics tests forbids by name.
- **Pair on each task's pass@1 rate instead.** Rejected as arithmetic, not as taste: a per-task
  rate is not a Bernoulli outcome, so there are no discordant pairs and McNemar does not apply to
  it at all.
- **Define "solved" as "a majority of trials passed".** One expression shorter than pass^n and
  slightly more forgiving. Rejected: it introduces a third definition of success into a report
  that already prints two, and nothing ranks on it.
- **Add a third `VerdictReason` so a significant p can break a tie the intervals cannot.** This is
  the alternative the second half of the Decision exists to refuse. Rejected: it is exactly
  ADR-0005's failure mode, arrived at by a route that looks statistical rather than editorial.
- **Skip the test when the intervals already separate** — it has nothing left to decide there.
  Rejected: the report's contents would then depend on its own verdict, and SPEC §4 asks for the
  paired comparison unconditionally.
- **Take scipy for `binomtest`.** Rejected without much deliberation: a scientific stack as a
  runtime dependency, for four lines of integer arithmetic this repository can verify by hand.

## Consequences
**A report will sometimes print a small p and refuse to name a winner in the same breath**, and
that pairing is the point rather than an embarrassment. It is also the sentence most likely to be
misread, so the renderers state the reading in prose rather than printing a bare number; the
wording is fixed in the next work package and JSON carries the model with no prose, which is
ADR-0005's rule about where an English sentence may live.

**The p is conservative, deliberately.** A reader comparing Assay's number against a mid-p or
chi-square figure from elsewhere will find Assay's is larger on the same counts. That is this
decision, not a defect, and it should not be "corrected" without superseding this record.

**Exactness has no crossover to maintain.** `math.comb` is exact at any count, so there is no
sample size at which the implementation switches to an approximation and no threshold constant to
get wrong. The cost is a sum of at most `min(b, c) + 1` terms, per pair of tools, per report.

**The test is silent by construction in two cases, and both are honest.** No shared tasks at all
means no comparison; equal discordant counts mean a p of exactly 1. Neither is an error and
neither is a missing value — the model carries the counts alongside the p, so a reader can see
which case they are in.

**Ranking is now the only thing in the report that two statistics could disagree about, and it is
settled in advance.** The Wilson intervals decide it, alone, as they have since ADR-0005. Anything
that wants to change that has to say so in a record that names ADR-0005 and supersedes it —
which is the check this ADR exists to leave behind.
