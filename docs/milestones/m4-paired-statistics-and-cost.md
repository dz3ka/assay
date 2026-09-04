# M4: paired statistics and cost accounting, computed over the free oracles

**Date:** 2026-09-04 · **Assay at:** M4 working tree (on `d877e31`) · **Milestone:** M4, SPEC §7's
paired significance test, bootstrap interval on pass@1, and cost per solved task

M4 adds three things to `assay report` and withdraws one promise from the front page. It answers
one question: **does the report now carry the statistics and the arithmetic a reader needs to
judge a comparison — a band on pass@1, a paired test on pass^n, and what a solved task cost?** It
answers yes, on machinery.

**It answers nothing about any tool, because no model was called.** Read §2 before quoting anything
from §3.

## 1. What was built, and what was run

Four decisions landed, each with its record:

| | |
|---|---|
| [ADR-0042](../adr/0042-the-readme-withdraws-the-promise-of-a-live-run.md) | The README withdraws the promise of a live run; no milestone owns it |
| [ADR-0043](../adr/0043-pass-at-1-is-a-percentile-bootstrap-over-tasks.md) | pass@1 gets a seeded percentile bootstrap over tasks; M0's marker dies |
| [ADR-0044](../adr/0044-the-paired-test-is-exact-mcnemar-on-pass-caret-n.md) | The paired test is exact McNemar on pass^n, and a significant p names no winner |
| [ADR-0046](../adr/0046-a-cost-line-carries-the-reason-it-has-no-dollars.md) | A cost line carries the reason it has no dollars; prices arrive at report time |

What was *run* is `assay report`, twice, over two hand-authored fixture result sets, one of
which **M4 itself enlarged** (stated in full below):

```
uv run --frozen assay report --results tests/fixtures/results_disjoint.json
uv run --frozen assay report --results tests/fixtures/results_overlapping.json
```

**No suite was mined in M4, no `assay run` was executed, and no trial was recorded.** Nothing here
produced a measurement; it produced the arithmetic a measurement will be read through. The
validation is hand-computed fixtures — `tests/stats/test_bootstrap.py` and `test_mcnemar.py` check
against values worked out by hand, in the style `test_wilson.py` established — plus the two free
oracles' results, which cost nothing because neither oracle asks anything of a model.

### The yield, stated as a yield

**M4's own yield is zero commits examined and zero valid tasks, because M4 walked no repository.**
That is the honest form of a milestone that mined nothing, and it is stated rather than omitted so
that the suites below are not read as M4's work.

The result sets M4's statistics were computed over come from earlier milestones and from fixtures:

- The fixture repository, mined and run in M3: **11 single-parent commits examined → 2 valid
  tasks**, 7 candidates reaching the gate, 0 unprovisioned
  ([`m3-oracle-run.md`](m3-oracle-run.md), which reproduces `tests/fixture_repo.EXPECTED_YIELD`).
- httpie, walked by hand twice: **743 single-parent commits examined → 0 valid tasks**, both times
  ([`m1-yield-httpie.md`](m1-yield-httpie.md), [`m2-yield-httpie-pinned.md`](m2-yield-httpie-pinned.md)).
  M2's pinned images moved 125 of those commits (16.8%) into `unprovisioned` without lifting the
  reach limit. That blocker is **untouched by M4**, as it was untouched by M3.
- `tests/fixtures/results_disjoint.json` (5 tasks × 2 trials × 2 adapters = 20 recorded trials) and
  `tests/fixtures/results_overlapping.json`, which are **hand-authored documents, not runs**. They
  exist so the renderers can be tested against a shape no oracle happens to produce.
- **M4 extended `results_disjoint.json` from 2 tasks to 5**, and that change is part of this
  milestone's diff rather than an input it found. The reason is a property of the test, not a
  preference about the answer: two-sided exact McNemar cannot return a p below 0.0625 with fewer
  than 5 discordant tasks, so at the old 2-task shape the paired test could never clear any
  threshold, and the Wilson bands over pass^n overlapped. Every figure printed in section 3 is
  therefore computed over a fixture this milestone reshaped. It is stated here because a document
  about measurement honesty cannot describe its own input as untouched.

## 2. What this milestone does NOT buy

**No model was called during M4. Not once, on any path, by any adapter, in any test, on any
developer machine.** No API key was set. No token was bought. Nothing in this milestone establishes
anything at all about a tool.

This is the statement [ADR-0042](../adr/0042-the-readme-withdraws-the-promise-of-a-live-run.md) says
is "owed at greater length by M4's milestone record", so it is owed in full here:

- The naive baseline (`src/assay/adapters/naive.py`) and the agentic Claude Code adapter
  (`src/assay/adapters/agentic.py`) remain **built, unit-tested against fakes, container-tested,
  and never once measured live**. M3 said this; M4 changes not one word of it.
- **There is still no naive-vs-agentic comparison in this repository.** The paired test M4 adds is
  the instrument for making one. It has never been pointed at one.
- Every McNemar p and every bootstrap band printed anywhere in this repository was computed over
  the ground-truth adapter, the null adapter, or a hand-written fixture. **None was computed over a
  tool that answered a prompt.**
- The in-container `api.anthropic.com` allowlist is still unexercised against the real endpoint.
- **The cost path has never priced a real spend, and cannot yet.** `ground_truth.py`, `null.py` and
  `agentic.py` all hard-code zero input and output tokens; `naive.py` is the only adapter that
  records what an API reported, and it has never called one. The token counts in §3's priced
  example are fixture data — numbers typed into a JSON file by hand, not tokens anybody was billed
  for.

This was a deliberate call, not an oversight: user ruling 1 for M4 cut the paid live run again,
after M3's ruling 12 cut it the first time. **M3 said "the first live run is M4's", and M4 is not
it.** That sentence is withdrawn from the README rather than quietly deleted, and **no milestone
owns the live run** — there is no date to give, and supplying one for the reader's comfort is
exactly what ADR-0042 refuses.

## 3. The result

Over `results_disjoint.json`, the two statistics and the default cost section:

```
Tools (two bands by two methods, both 95%: pass^n is a Wilson score interval over tasks; pass@1
is a mean of per-task rates rather than a proportion, so its band is a seeded percentile bootstrap
over tasks (2000 resamples, seed 20260904))
  null          trials=10  pass@1=0.000  pass@1 interval=[0.000, 0.000]  pass^n=0.000  pass^n interval=[0.000, 0.434]
  ground-truth  trials=10  pass@1=1.000  pass@1 interval=[1.000, 1.000]  pass^n=1.000  pass^n interval=[0.566, 1.000]

Comparisons
  null vs ground-truth: Winner: ground-truth - its pass^n confidence interval is entirely above the other's.
    null solved 0 tasks ground-truth did not, and ground-truth solved 5 null did not (exact
    McNemar p = 0.0625). This measures whether they differ, not which ranks higher - ranking is
    the pass^n intervals' decision alone.
```

The caption is the point of ADR-0043: two bands sitting side by side, computed by two different
procedures, would otherwise read as one. M0's `_PASS_AT_1_NO_INTERVAL` marker is gone, replaced by
a statement of both methods rather than by silence.

### The p is printed beside the verdict, and neither direction lets it move the ranking

The two committed fixtures happen to bracket the case ADR-0044 exists for. Above, the Wilson bands
separate, so `decide_verdict` names ground-truth the winner — while the
paired p is **0.0625, not significant at 0.05**. On `results_overlapping.json` the reverse shape:
`No winner: the pass^n confidence intervals overlap`, beside `exact McNemar p = 1.0000`.

Neither number was allowed to touch the other. `Verdict` still carries exactly two reasons,
`decide_verdict` is untouched by M4, and the p is rendered as a sentence that says what it does and
does not mean. A significant p with overlapping bands is a real and printable finding — *the tools
differ on the tasks they share, and neither tool's own rate is pinned down well enough to rank
them* — and it is not a licence. Letting the more permissive of two statistics unlock the winner
claim is [ADR-0005](../adr/0005-no-winner-when-intervals-overlap.md)'s failure mode with an
extra step.

There is also an honest bound worth stating: with 5 discordant tasks the smallest two-sided exact
p attainable is 2 × 0.5⁵ = 0.0625, so **a suite this small cannot produce a significant paired
result at all**, however lopsided the tools. That is a fact about the suite, not about the test.

### The priced path, priced with an invented rate card

**Everything in this subsection is fiction.** The rates below were chosen arbitrarily and
quoted from nowhere, precisely so that no reader, and no future maintainer, can mistake them for
a quote. **Assay stores no prices**: not in code, not in a
fixture, not in a result set. They are typed on the command line, and the report names where the
caller said they came from ([ADR-0046](../adr/0046-a-cost-line-carries-the-reason-it-has-no-dollars.md)).

```
uv run --frozen assay report --results tests/fixtures/results_disjoint.json \
  --price ground-truth=100/200 --price null=100/200 \
  --prices-source "illustrative, not a real quote"
```

```
Costs (prices as supplied: illustrative, not a real quote; dollars are the prices supplied with
this report, per million tokens, and Assay knows no others; a total covers every recorded trial,
errored ones included; cost ranks nothing - the pass^n intervals decide that alone)
  null          input=0  output=0  solved=0  rates=$100.000000 in / $200.000000 out per MTok  total=-  per solved task=-
    null recorded no tokens, so what it spent is unknown rather than zero - every adapter Assay
    ships today reports zero here
  ground-truth  input=10240  output=960  solved=5  rates=$100.000000 in / $200.000000 out per MTok  total=$1.216000  per solved task=$0.243200
    ground-truth is priced at the rates supplied with this report, and at nothing else
```

Two things in that output are the whole decision. The dollars are re-derivable from the report
alone — the rates that priced them are printed beside them — and **the priced null adapter prints
no total**. It recorded (0, 0) tokens, which is genuinely ambiguous between "spent nothing" and
"was never instrumented", so its basis is `no_tokens_recorded` and its dollars are suppressed
rather than rounded to a confident `$0.00`. The four bases — `no_price_supplied`,
`no_tokens_recorded`, `no_tasks_solved`, `priced` — each get a sentence, because a blank a reader
fills in is what ADR-0035 refuses. Cost enters no ranking path anywhere. Without `--price`, which
is every report this repository has produced to date, the section is still present and every line
reads `no price was supplied`.

## 4. Open flags carried into M5

M3's §4 flags are all still open — `model_api.py` never reading the served snapshot back,
`--network bridge` not being a hostname allowlist, the unverified `TRIAL_LIMITS` guesses, the
absence of resume, and the unlifted M2 reach limit. M4 touched none of them. New ones:

- **The bootstrap band is degenerate on the oracles.** Every task has an identical per-task rate
  (1.0 or 0.0), so every resample is identical and the band collapses to a point: `[1.000, 1.000]`
  and `[0.000, 0.000]` above. That is the correct output for a sample with no variation, and it
  means the interval's *width* has never been exercised on anything but hand-written fixtures.
- `BOOTSTRAP_SEED` and `BOOTSTRAP_RESAMPLES` are fixed module constants with no flag, deliberately
  (band-shopping is the failure this repo exists to refuse) — but that makes them a policy nobody
  has re-examined since the day they were written.
- The cost path is unexercised against a real spend, and will stay so until an adapter that records
  tokens actually runs.
- Prices are the caller's words. `--prices-source` is free text, so an attributable dollar figure
  is only as attributable as the caller was honest.

## 5. Reproducing this

1. `uv run --frozen assay report --results tests/fixtures/results_disjoint.json`
2. The same with the `--price` flags in §3, for the priced output.
3. `uv run --frozen assay report --results tests/fixtures/results_overlapping.json`

No Docker, no network and no API key are needed — which is the shortest true summary of this
milestone. The bootstrap seed is fixed, so the bands are identical between runs; if they are not,
something changed that an ADR should have.
