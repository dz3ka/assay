# ADR-0043: pass@1's band is a percentile bootstrap over tasks, drawn with `random()` from a fixed seed

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0035](0035-the-interval-is-on-pass-caret-n-over-tasks.md) settled that pass^n gets a Wilson
band whose denominator is the task count, and that pass@1 gets no band at all but an explicit
marker saying so. It also wrote the terms of its own expiry: pass@1's honest uncertainty is a
bootstrap over tasks, SPEC §7 puts that in M4, and "when M4 gives pass@1 a real interval, the
marker must die in that change." This record is the arithmetic that discharges it. It amends
ADR-0035 rather than superseding it, because the pre-authorisation was part of that decision.

pass@1 is the mean over tasks of each task's own pass rate, not a count of successes over a count
of attempts, so there is no proportion for Wilson to be an interval of. What it does have is a
sample: the tasks. The suite is what the miner happened to yield from one repository's history,
another run would have yielded a different handful, and the width worth reporting is how much the
score would move if it had. Resampling the tasks with replacement estimates that directly, and the
percentile method reads the band off the resampled means without assuming a distribution the rates
do not have.

Resampling raises a question Wilson never did, and it is the reason this record exists rather than
a comment: **the estimator has an input that is not data.** Wilson is a function of two integers,
so the same result set produces the same band forever. A bootstrap is that plus a stream of random
numbers, and unless the stream is pinned, two `assay report` runs over the same result file print
different bands. SPEC §5.5 makes reproducibility the point of the whole harness, and a number that
moves between runs on identical input is the one output this project cannot ship.

Pinning it needs two things, and only the first is obvious. The seed must be fixed, and the map
from seed to draws must be stable across Python versions. CPython's `random` module documents that
guarantee for exactly one method: given the same seed, `random()` continues to produce the same
sequence. `choice`, `choices`, `randrange` and `sample` are built on top of it by implementations
that are free to change, so a band computed with them is reproducible until an interpreter upgrade
and silently not afterwards. That failure has no symptom — the report still renders, and only the
published number moves.

The repository has no precedent to copy. Its one existing use of randomness is
`report/redact.py`'s `from_random()`, whose salt is deliberately *un*-reproducible and never
persisted ([ADR-0009](0009-redaction-is-hmac-with-a-per-render-salt.md)). So Assay now holds two
generators whose requirements are exact inverses, and which one a reader is looking at is not
something an inline comment can be trusted to keep straight.

## Decision
**pass@1's interval is a percentile bootstrap of the mean over tasks. Its generator is
`random.Random(seed)`, constructed inside `bootstrap_mean_interval`, and indices are drawn as
`int(rng.random() * n)` and by no other method. The seed and the resample count are fixed
constants at the call site — never a flag, never a default inside `stats`.**

The estimator: draw `n` tasks with replacement `n` times, take the mean of the values they name,
repeat `resamples` times, sort, and return the order statistics at `floor(tail * resamples)` and
`ceil((1 - tail) * resamples) - 1` for `tail = (1 - level) / 2`. No interpolation between
neighbouring means and no clamp to [0, 1]: both endpoints are means that were actually observed, so
the band cannot leave the range of the values, and `stats` is not told that these values are rates
([ADR-0035](0035-the-interval-is-on-pass-caret-n-over-tasks.md)'s one-way rule).

`rng.random()` is the whole draw contract, and it is a load-bearing restriction rather than a
style preference. It is the one documented cross-version-stable draw, so a band published today is
recomputable on any 3.12-or-later interpreter. `tests/stats/test_bootstrap.py` pins one measured
band for one `(values, seed)` as a change detector: every other expectation in that file is derived
from the binomial cells of the resample mean and would stay green under a different draw, so the
pinned one is what fails if the contract is broken — and this record is what it must supersede.

**There is no `--seed` flag and there will not be one.** A seed exposed at the command line is a
knob on a measurement: run the report five times, keep the run where the bands separate, and the
harness has become the thing it exists to detect. The seed is not a parameter of what was measured
— it is what makes the arithmetic deterministic — so it belongs in the source, where changing it is
a diff a reviewer sees rather than a shell history nobody keeps.

`seed` and `resamples` are keyword-only and have no defaults in `stats`. A leaf that imports
nothing from Assay has no standing to decide how many resamples a published report is worth; the
report is what spends them, so `BOOTSTRAP_SEED` and `BOOTSTRAP_RESAMPLES` live beside the call in
`report/model.py`, following the pattern `sandbox/models.py` states for its own limits. Wiring the
band into the report — and deleting ADR-0035's no-interval marker, which stays until then — is the
next work package in this milestone, not this one.

The report will then carry two bands computed by two different methods, so ADR-0035's rule that an
asymmetry is stated rather than left silent binds the replacement too: the caption names Wilson for
pass^n and the bootstrap for pass@1, because two intervals side by side otherwise read as one
instrument.

## Alternatives considered
- **A normal or Student-t interval on the per-task rates:** `mean ± t·s/√n`, closed form, hand
  computable, and no generator at all — which would have made this entire record unnecessary, and
  makes it the strongest rejected option. It fails on the data this harness produces: pass rates are
  bounded in [0, 1] and pile up at both ends, and the two adapters that bracket every report are
  all-1 and all-0. There the sample standard deviation is zero, so a symmetric interval reports
  zero width — certainty from five observations — and near the ends it reaches outside the unit
  interval. That is the same defect that banned the normal approximation for proportions in
  CLAUDE.md, and it does not become acceptable by being applied to a mean instead.
- **The BCa (bias-corrected and accelerated) bootstrap.** Better coverage than the percentile
  method on a skewed resample distribution, which at small task counts is what this is. Rejected on
  what it costs to verify: an inverse normal CDF plus a jackknife acceleration term, in a repository
  that deliberately spells `Z_95` as a literal rather than take a distribution as a dependency for
  one constant. Forty lines of numerics checkable only against another implementation is the shape
  of code this project refuses, and the percentile band is the more conservative of the two.
- **Pool the trials into a proportion and give pass@1 a Wilson band too.** Rejected again, for
  ADR-0035's reason and not a new one: it would print a band computed from a different number than
  the one beside it, and a reader who checked would find they disagree.
- **Take a `random.Random` as an argument, or seed the `random` module globally.** Rejected. Both
  move the reproducibility guarantee out to the callers: the first one to pass a generator it had
  already drawn from — or any unrelated module touching the shared one — makes the published band a
  function of call order, reproducible only for someone who knows what ran before it.
- **`rng.choices(values, k=n)`, the natural spelling.** One line, obviously correct, and not
  covered by CPython's reproducibility note. It buys brevity with the one property the band exists
  to have.
- **Expose `--seed` (or `--resamples`) so a run can be varied.** Rejected as band-shopping, above.
  A future milestone that needs different numbers changes the constants and supersedes this record.
- **Default the seed and resample count inside `stats`.** Rejected: it hides the two inputs that
  decide the printed band inside a package the report never has to name, and makes a leaf the owner
  of a policy whose consequences it cannot see.
- **Assert the band against a golden file of resampled means.** Rejected. This repository has no
  snapshot fixtures anywhere, and a golden artifact is a measured value nobody re-derives; one
  pinned literal beside the derivation of every other expectation detects the same change.

## Consequences
**pass@1 stops being the number with no band, and ADR-0035's marker becomes deletable.** Until the
wiring lands, the marker still prints and is still true; the sequence is deliberate, because a
milestone that deleted the disclaimer before the band existed would be the exact failure the
disclaimer was written to prevent.

**The band will look coarse on small suites, and that is the estimator being honest.** With two
tasks a resample mean can only be 0, 0.5 or 1, so the 95% band is the entire unit interval — the
same thing ADR-0035 found when the oracle bracket failed to separate at two tasks. A bootstrap
cannot manufacture information the suite does not contain, and a smooth-looking band at n=2 would
mean it had.

**A CPython change to `random()` breaks one test loudly.** That is the intended alarm, and the
answer to it is a new decision, not a re-measured literal: the pinned band in
`tests/stats/test_bootstrap.py` names this ADR as what has to be superseded first.

**The cost is a pure-Python loop, `resamples × tasks` draws per tool per report**, a fraction of a
second at the sizes this harness mines. pydantic stays the only runtime dependency; nothing here
reaches for numpy.

**Assay now holds two generators with opposite requirements**, and both are on the record: the
redaction salt must never be reproducible ([ADR-0009](0009-redaction-is-hmac-with-a-per-render-salt.md)),
and this band must always be. A reader who finds a seeded generator in this codebase can tell which
rule it is under by which record names it.
