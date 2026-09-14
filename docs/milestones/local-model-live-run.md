# The local-model live run, pre-registered before it happens

**Written:** 2026-09-09 · **Assay at:** the local-baseline working tree (on `72e560d`, plus the
uncommitted `naive-local` packages) · **Milestone:** none — M0–M5 are complete and no milestone owns
the live run ([ADR-0051](../adr/0051-m5s-two-tools-are-two-oracles.md))

This document exists to answer one question: **what does a small model served on this machine
score, against a suite mined from a repository Assay was not built for?** It does not answer it
yet. The run described below has not been performed. Nothing in this repository has ever called a
model, which is the standing fact the milestone records in this directory already carry, and this
file does not change it.

What the file is for is fixing the run's terms while no number exists. The model, the suite, the
trial count and the rule for stopping are written here first so that none of them can be chosen
after seeing a result. That ordering is the whole value of the document; a pre-registration written
afterwards is not a pre-registration, it is a rationalisation with a date on it.

**This file has one section, and the two that are missing are missing on purpose.** A run that had
happened would carry a §2 — *what this run does NOT establish* — and a §3 — the figures, in that
order, because [ADR-0051](../adr/0051-m5s-two-tools-are-two-oracles.md) makes the disclosure sitting
above the numbers the substance of a decision rather than its presentation ("Ordering is the
substance of this decision, not its presentation", ADR-0051's Decision). Neither is stubbed here,
because an empty heading would invite exactly the misreading this file must not permit: **this is
not a run that produced no result. It is a run that has not been made.** The blocker is a daemon
that is not installed on this machine, not a measurement that came back empty.

> **Amended 2026-09-11.** Everything above was written on 2026-09-09, when the run had not been
> made, and is kept as written. It is no longer current: the run was made on 2026-09-11. The file
> now has four sections — the pre-registration (§1), the wiring smoke (§2), what the discarded
> first attempt cost (§3) and the figures (§4) — in that order, disclosure before numbers, per
> [ADR-0051](../adr/0051-m5s-two-tools-are-two-oracles.md). **Nothing in §1 was edited to match
> what came out.**

## 1. The pre-registration

**One model, and it is chosen now.** `qwen2.5-coder:7b`, served by Ollama on loopback. It is not
selectable from the command line: `DEFAULT_LOCAL_MODEL` and `LOCAL_MODEL_ENDPOINT` are compiled-in
constants in `src/assay/cli/main.py` (lines 199 and 209), and `--model` is not read on the local
path at all — it names a hosted alias a local daemon has never heard of
([ADR-0061](../adr/0061-the-local-baseline-is-the-substitute-adr-0051-rejected.md)). So the run's
command line will not carry the model's name, and this paragraph is where the choice is recorded.
The result set will still say which model answered: the adapter's version string is the harness
version with the model appended (`src/assay/adapters/naive.py:122`), and it is written onto every
attempt.

**The choice was made from the model's public description and from nothing observed here.** The
constant's own comment says so. There is no benchmark behind it, no prior local run to compare it
to, and no expectation recorded for what it will score — deliberately, because a recorded
expectation is a threshold, and a threshold written before the run is a thing a later reading can
be argued against.

**Three adapters, and the two extra ones are the bracket, not competitors.**

```
uv run --frozen assay run --suite <tenacity.json> --repo <clone> --out <results.json> \
  --adapter ground-truth --adapter null --adapter naive-local --trials 5
uv run --frozen assay report --results <results.json>
```

`ground-truth` and `null` are oracles: they answer from the task itself and their outcomes are
known before they run, which is what makes them a bracket rather than evidence
([ADR-0051](../adr/0051-m5s-two-tools-are-two-oracles.md)). `naive-local` is the only row in that
command whose outcome is unknown. The run names no tool, so it passes `_adapter_refusal` without a
metered call and spends nothing — the exemption
[ADR-0060](../adr/0060-the-local-baseline-is-exempt-and-does-not-discharge-the-rule.md) decided, and
the same record fixes its limit: **the local baseline is exempt from being asked for a baseline, and
it does not supply one.** This run therefore cannot produce a tool number, and no wording in §2 or
§3 will be allowed to imply that it did.

**Five trials per task per adapter**, `--trials 5`, which is the project default and is not being
tuned for this run.

**The suite: `jd/tenacity`, re-mined with `--limit 200`.**

```
git clone https://github.com/jd/tenacity.git
git -C <clone> checkout 3e58094d3bc414975aad9eadf343a32bdb3b89b3
uv run --frozen assay mine --repo <clone> --out <tenacity.json> --name tenacity --limit 200
```

The clone HEAD and the walk limit are the ones
[`m5-yield-public-repos.md`](m5-yield-public-repos.md) §2 recorded, because a suite mined from a
different range is a different suite.

**The suite hash this run expects, and where it comes from.** The expectation is:

```
sha256:f00d81732e3389728b44fd69bc479fcafba4b1085fdb12bfe33336bb3feb1106
```

with 13 tasks in it. **That is a claim inherited from a prior run, not a fact re-derived for this
document.** Its single source is
[`m5-yield-public-repos.md`](m5-yield-public-repos.md) §3, whose table records it against the
tenacity mine of 2026-09-07, and nothing has re-run that mine since. It is written here as the
pre-registered expectation so that the re-mine has something to disagree with — not as a verified
input. The hash *should* reproduce, since `repo_url` for this clone is its declared `origin` rather
than a host path ([ADR-0052](../adr/0052-a-repository-with-no-remote-names-itself-by-its-root-commit.md)),
but "should" is the reason to check rather than a substitute for checking.

**Pre-committed, in case it does not reproduce:** the re-mined hash and the task count that came out
are published, beside the two above, with the delta named. Toolchain drift and flaky tests are both
live possibilities on a walk that runs a third party's suite on the host. **The substitution is
never made silently, and the expectation above is never edited to match what arrived.** A hash
quietly replaced is a content address that has stopped addressing anything, which is the whole
property [ADR-0007](../adr/0007-suites-are-content-addressed-and-versioned.md) bought and this
file will not spend.

**The stop rule.** It has the shape
[ADR-0021](../adr/0021-resolution-is-pinned-to-the-base-commit-era.md) used on the one widening it
allowed itself — chosen before the measurement, written down first, and honoured when the result
arrived rather than argued with ([ADR-0025](../adr/0025-the-one-widening-is-spent.md), which spent
that budget and published the number as it came out):

> One model, chosen before the run and named above. Whatever pass^n comes out is published as it
> came out, **including 0.000**. A zero is a finding about what a small local model does against a
> suite mined from a real repository, and it is published as one. A second model is a new decision
> with its own ADR — not a re-roll, not a retry, and not something an implementer may reach for
> because the first figure looked poor.

**0.000 is an outcome this document has already agreed to publish.** If the local baseline scores
zero it sits *on* the bracket rather than strictly inside it, and the question at the top of this
file gets a real answer that is also an unflattering one: the wiring is proven and the model solved
nothing. That is a result, and it is published in the same words a better one would be. Changing
the model at that point would be choosing the opponent after seeing the score, which is the failure
[ADR-0060](../adr/0060-the-local-baseline-is-exempt-and-does-not-discharge-the-rule.md) refuses in
code and this rule refuses in writing.

**What is left to do before any of this can run.** Ollama installed on this machine, the model
pulled, and the daemon listening on the endpoint the constant names. The response shape the adapter
parses is still read from documentation rather than from anything a daemon has returned
([ADR-0059](../adr/0059-a-local-model-gets-its-own-transport-not-a-wider-allowlist.md)), so the
first honest outcome of the run may be that the parse is wrong — and that, too, gets written down
here rather than fixed quietly on the way to a number.

> **Amended 2026-09-09.** The paragraph above stands as pre-registered on 2026-09-08 and is no
> longer current: Ollama is installed, the model is pulled, the daemon answers, and the parse was
> not wrong. §2 records what was actually measured. Nothing in §1 was edited to match the outcome.

## 2. What the wiring did when it was first pointed at a live daemon

This section is disclosure, not results. It sits above the figures because
[ADR-0051](../adr/0051-m5s-two-tools-are-two-oracles.md) requires what a run could
not establish to be read before them. As written on 2026-09-09 this paragraph said that the scored
run at `--trials 5` against the `jd/tenacity` suite **had not been run yet**; it was run on
2026-09-11, and its figures are in §4, behind the second disclosure in §3. Everything below is a
smoke test on the fixture repository at `--trials 1`, and it settles wiring questions only.

**It is not evidence about how well the model scores.** Different suite, different tasks, n=1.

**What ran.** On 2026-09-09 the fixture suite was mined, validated, run against three adapters and
reported, through the real CLI. All five commands exited 0. Measured by a throwaway driver that
builds `tests.fixture_repo.build_fixture_repo` into a scratch directory and calls `assay.cli.main`
the way `scripts/demo.py` does; the driver is not a repository deliverable and was not kept.

| command | result | wall clock |
|---|---|---|
| `mine --test-timeout-s 120` | 11 single-parent commits examined → **2 valid tasks**; 7 candidates reached the gate | 147.3 s |
| `validate` | 2 of 2 tasks revalidate | 8.2 s |
| `run` — `ground-truth`, `null`, `naive-local`, `--trials 1` | 6 trials recorded | 53.2 s |
| `report` (text / HTML) | 2591 / 5200 chars | 0.3 s each |

**The oracle bracket held:** `ground-truth` passed both tasks, `null` failed both.

**The model was really called, and this is the load-bearing check.** 53.2 s looked too fast for two
7B completions, so the trial records were read rather than the exit code trusted. From
`results.json`, per trial: `adapter_version = "0.1.0+qwen2.5-coder:7b"`, `cost_usd = "0.000000"`,
`error = null`, `retries = 0`; task `522ebe0b013a` at 275 input / 264 output tokens in 18.0 s, task
`b209fc7be9b5` at 237 / 231 in 12.3 s. Both carry a real unified diff the model wrote.

**`naive-local` failed both tasks, and the failures are the model's, not the harness's.** The first
patch adds a `from tests.conftest import pytest` that does not exist; the second leaves a stray
closing fence and duplicates an assertion. That distinction is the entire purpose of a smoke and it
is the reason a 0-for-2 here is not read as broken wiring.

**The response-shape assumption is retired, and only as far as the evidence goes.**
[ADR-0059](../adr/0059-a-local-model-gets-its-own-transport-not-a-wider-allowlist.md) recorded that
`_parse_chat_completion` was written from Ollama's documentation with no daemon having answered.
A daemon has now answered: every field the parser reads was present and well-typed on real bodies,
which parsed without raising, and **the parser needed no correction**. The check ADR-0059 asked for
and did not get is the literal one — the raw bodies were not retained, so the `GOOD_CHAT_BODY`
fixture has not been diffed against a recorded body byte for byte. The fields are measured; the
literal is not. All three sites that carried the old claim were amended to say that and no more.

**Two things the smoke did not establish.** It did not exercise the timeout margin near its limit:
outputs were 264 and 231 tokens against an 8192-token budget and 12–18 s against a 900 s trial
timeout, so the earlier ~438 s worst-case estimate stands as an untested upper bound rather than a
measured one. And it says nothing about the pre-registered suite, which is a different repository
and a different mine.

> **Amended 2026-09-11.** The paragraph above ended, as written on 2026-09-09, with the claim that
> the pre-registered suite's content hash "has not been re-derived since 2026-09-07". That clause is
> struck, because it is no longer true: the suite the scored run used was mined on 2026-09-10 and
> its body hashes to exactly the address §1 pre-registered, on 13 tasks. §4 records that
> re-derivation. The rest of the paragraph stands — the timeout margin is measured further in §4
> and still nowhere near its limit.

**What changed in the harness between the pre-registration and the re-attempt, and what did not.**
The smoke above was not the last thing that happened. On 2026-09-10 the pre-registered
`jd/tenacity` run was launched for the first time, ran for **16 minutes 52 seconds**, and ended on a
task whose image would not build, having written nothing —
*(this sentence read "ran for over an hour" until the correction dated 2026-09-11 recorded in §3
below; the retained stamps are the artifact and the hour was corroborated by nothing that was kept.
The original wording is quoted in §3 rather than erased here.)* —
[ADR-0069](../adr/0069-the-result-set-is-written-after-every-task.md) records the 105 already-scored
trials that went with it, and that figure is quoted from the record rather than re-derived here. **No
figure came out of that attempt and none is claimed from it**; what came out of it were four
decisions, every one of them about what a run *records* rather than about what it measures.
[ADR-0067](../adr/0067-the-result-set-carries-its-own-denominator-and-names-what-it-could-not-measure.md)
put the denominator into the result set itself — `suite_task_count`, required, beside an
`unprovisioned` map of task id to the sentence that failed it (`src/assay/results/models.py:223`
and `:227`).
[ADR-0068](../adr/0068-one-unprovisioned-state-for-both-causes-and-a-partial-task-is-discarded-whole.md)
made a task that cannot be provisioned a recorded state rather than the end of the run, discarding
that task's own trials whole and returning success only if something was measured
(`src/assay/cli/main.py:1175` and `:1213`).
[ADR-0069](../adr/0069-the-result-set-is-written-after-every-task.md) moved the write from once at
the end to once before the first task and once after every task (`src/assay/cli/main.py:1132` and
`:1185`), so an interrupted run keeps what it measured.
[ADR-0070](../adr/0070-the-report-publishes-its-coverage-and-names-what-it-could-not-measure.md) put
one coverage sentence into both prose formats on every report, including the run that missed nothing
(`_coverage_statement`, `src/assay/report/render.py:133`, read by the text renderer at `:308` and
the HTML renderer at `:542`). **None of the four touched a term §1 pre-registered.** The suite is the
same one — `jd/tenacity` at the same clone HEAD, the same `--limit 200` walk, the same 13 tasks and
the same expected hash — because
[ADR-0066](../adr/0066-the-provisioning-asymmetry-gets-a-milestone-not-a-deferral.md) sequenced the
mining change that would produce a different one *after* this run, for exactly that reason; the
three adapters and their roles are unchanged; `--trials 5` is still the project default
(`DEFAULT_TRIALS = 5`, `src/assay/cli/main.py:170`); the endpoint and model are still compiled-in
constants, in that order, at the two lines §1 cites (`:199` and `:209`); and the stop rule is untouched, since
nothing above it is a rule about what gets published. What the four records do add is a disclosure §1
never carried: the re-attempt may publish **fewer than the suite's 13 tasks**, and when it does, the
report states how many it measured and names the ones it did not. That is a term §1 is silent on
rather than one it fixed and this file has since relaxed — whatever pass^n comes out is still
published as it came out, including 0.000, now over a denominator the page prints instead of one the
reader is left to assume.

## 3. What the discarded first attempt cost, and why the re-run is not a re-roll

This section sits above the figures for the same reason §2 does. A reader deciding how much to trust
a pass^n has to know first that the run which produced it was the second launch and not the first,
and what became of the first
([ADR-0051](../adr/0051-m5s-two-tools-are-two-oracles.md)). §2's closing paragraph mentions that
attempt in passing, on the way to describing four decisions. **That mention is not the disclosure.
This section is.**

**What was attempted on 2026-09-10.** Two launches, both on the terms §1 fixed — the same suite
file, the same three adapters, `--trials 5` — and both against the suite mined that morning, before
either of them started.

| launch (UTC) | how it ended | what it scored |
|---|---|---|
| 04:23:40 → 04:23:49 | `docker build` failed on the first task it reached; the run stopped and wrote no result file | nothing |
| 12:31:35 → 12:48:27 | 105 trials scored, then `docker build` failed on the eighth task; the run stopped and wrote no result file | 105 trials, every one discarded |

**The loss figure, and how it is established rather than asserted.** The run log kept from the
second launch carries 105 numbered trial lines across 7 distinct task ids, the last of them
`[ 105/195] tenacity-78c8d4bc8596 naive-local trial 5/5: failed`. The denominator in those brackets
is the pre-registered arithmetic — 13 tasks × 3 adapters × 5 trials = 195 — and 7 tasks completed at
3 × 5 apiece is 105. **The figure is 105 scored trials, of which 35 were `naive-local` completions
the model had really produced.** It is derived here from the log's own lines and from §1's trial
count, and it agrees with the 105 that
[ADR-0069](../adr/0069-the-result-set-is-written-after-every-task.md) records; the agreement is a
check on that record, not its source.

**What was lost is the record, not the observation, and the difference matters.** The log preserves
each of the 105 verdicts — the oracle bracket held through all 7 tasks and `naive-local` failed all
35 of its trials. What it does not preserve is anything that makes a verdict a result: no diff, no
token counts, no adapter version string, no content address tying the trial to a suite. So **no
figure from that attempt is publishable, none is published, and none of it is reused in §4** — the
165 trials below were all scored fresh on 2026-09-11. The honest form of the loss is that sentence
and not a softer one.

**One figure in the record that the artifacts do not support.** §2 above and ADR-0069 both describe
that attempt as having "ran for over an hour". The start and finish stamps retained for it are
2026-09-10T12:31:35Z and 12:48:27Z — **16 minutes 52 seconds** — and the run log's own modification
time falls inside that window. At the rate §4 measured (165 trials in 22 min 28 s), 105 trials is
about 14 minutes, which fits the stamps and does not fit an hour. The stamps are the artifact; the
hour is corroborated by nothing that was kept.

**The correction has since been applied to both places that carried the claim**, on 2026-09-11, in
the amend-don't-delete style this directory uses: §2 above now states the measured figure and quotes
the wording it replaced, and
[ADR-0069](../adr/0069-the-result-set-is-written-after-every-task.md) carries a dated amendment note
above its Context that corrects both the "over an hour" sentence and the "measured in hours" cost
argument in its Consequences, leaving the original words of each as written. When this paragraph was
first drafted the correction was deliberately recorded here and *not* applied, because a number
corrected in one place while standing in two is worse than one correction read beside the claim;
that reason expired once both places were amended in the same pass.

**No decision moves.** ADR-0069 decides that the result set is written after every task, and that
rests on 105 scored trials being lost to a single end-of-run write — a figure established by
`grep -cE '^\[ *[0-9]+/195\]'` over the retained log and by the pre-registered arithmetic
7 × 3 × 5, neither of which depends on the run's duration.

**What changed in the code in response, and what did not.** Four records, and §2 names their sites
line by line: [ADR-0067](../adr/0067-the-result-set-carries-its-own-denominator-and-names-what-it-could-not-measure.md)
put the denominator into the result set,
[ADR-0068](../adr/0068-one-unprovisioned-state-for-both-causes-and-a-partial-task-is-discarded-whole.md)
made an unprovisionable task a recorded state instead of the end of the run,
[ADR-0069](../adr/0069-the-result-set-is-written-after-every-task.md) moved the write to once after
every task, and
[ADR-0070](../adr/0070-the-report-publishes-its-coverage-and-names-what-it-could-not-measure.md) put
a coverage sentence on every report. **All four change what a run records. None changes what it
measures.** The adapter, the transport, the prompt and the model were not touched between the two
attempts: `src/assay/adapters/naive.py` and `src/assay/host/model_api.py` were both last modified on
2026-09-09, before either launch — modification times are weak evidence and are named here as what
they are.

**Why the re-run stands on identical pre-registered terms.** The suite is the same *file* rather than
a fresh mine: generated 2026-09-10T04:22:14Z, before either launch, and re-verified against the same
content address by the 2026-09-11 run. The three adapters and their roles are unchanged, `--trials 5`
is still `DEFAULT_TRIALS` (`src/assay/cli/main.py:170`), the endpoint and model are still the
compiled-in constants at `:199` and `:209` that §1 cites, and the stop rule is untouched. **What a
re-roll would look like is absent**: nothing was tuned, no term was moved, and the only changes were
to recording. But the claim stops short of one it is not entitled to — **the second launch was not
blind.** The first attempt's log shows 35 failed `naive-local` trials, so whoever launched the second
knew the model was scoring nothing through the first seven tasks. That is exactly the situation §1's
stop rule was written on 2026-09-08 to bind, and it binds: the model was not changed, the suite was
not re-mined, and the figure below is published as it came out.

## 4. The scored run, 2026-09-11

**What ran.**

| | |
|---|---|
| started → finished (UTC) | 2026-09-11T08:23:50Z → 08:46:18Z, **22 min 28 s** |
| exit status | 0 |
| trials recorded | **165** — 11 tasks × 3 adapters × 5 trials |
| trials the suite called for | 195 — 13 × 3 × 5 |
| model | `qwen2.5-coder:7b`, written onto all 55 local attempts as `adapter_version = "0.1.0+qwen2.5-coder:7b"` |
| spend | `cost_usd = "0.000000"` on every one of the 55 |

The 30 trials missing from those 195 are the two unprovisioned tasks' own, discarded whole rather
than recorded as failures
([ADR-0068](../adr/0068-one-unprovisioned-state-for-both-causes-and-a-partial-task-is-discarded-whole.md)).

**The suite reproduced its pre-registered address, so §1's substitution clause never fired.** The
suite file the run used hashes to

```
sha256:f00d81732e3389728b44fd69bc479fcafba4b1085fdb12bfe33336bb3feb1106
```

on 13 tasks under the name `tenacity` — re-derived for this write-up by loading the file through
`assay.suite.io.load_suite`, which recomputes the body digest and refuses the file outright if it
disagrees with the one recorded in it. §1 pre-committed to publishing the re-mined hash and task
count beside the expectation with the delta named. **There is no delta.** The expectation in §1 was
not edited, and did not need to be.

**The figures, as the report renders them.** Both bands are 95%: pass^n is a Wilson score interval
over tasks; pass@1 is a mean of per-task rates rather than a proportion, so its band is a seeded
percentile bootstrap over tasks (2000 resamples, seed 20260904).

| adapter | trials | pass@1 | pass@1 interval | pass^n | pass^n interval |
|---|---|---|---|---|---|
| `ground-truth` | 55 | 1.000 | [1.000, 1.000] | 1.000 | [0.741, 1.000] |
| `null` | 55 | 0.000 | [0.000, 0.000] | 0.000 | [0.000, 0.259] |
| `naive-local` | 55 | 0.000 | [0.000, 0.000] | 0.000 | [0.000, 0.259] |

**The coverage, in the report's own words:**

> Coverage: 11 of 13 tasks measured; 2 could not be provisioned and so appear in no number on this
> page

The report names the two by redaction token, and a token is drawn per render and means nothing
across renders; in the result set they are `tenacity-98f7da70f867` and `tenacity-a7f548520e4e`.
**The cause is one cause, and it is the harness's rather than the model's.** For both tasks the task
image failed to build: `uv pip install --exclude-newer <base-commit era> -e /workspace pytest`
resolved a `setuptools` that does `import distutils` on a Python 3.12 base image, where `distutils`
is no longer in the standard library. A `setuptools` floor would have rescued both builds, and
[ADR-0071](../adr/0071-the-setuptools-floor-is-declined-and-the-builds-it-would-have-rescued-are-reported.md)
declines it for good, so the two are reported here rather than patched. The two era pins are
2020-12-15 and 2021-07-07 — the
provisioning asymmetry
[ADR-0066](../adr/0066-the-provisioning-asymmetry-gets-a-milestone-not-a-deferral.md) sequenced
*after* this run rather than before it, showing up on schedule. Those two tasks are absent from every
number in the table above, and the page says so without being asked.

**The finding, in plain words.** `qwen2.5-coder:7b`, one call per trial and no agent loop, solved
**none of the 11 tasks it was measured on**: 0 of 55 trials passed, pass@1 = 0.000, pass^n = 0.000.
The oracles bracket it — `ground-truth` 11 of 11, `null` 0 of 11 — and **it sits on the bottom of
that bracket rather than inside it.** §1 agreed in advance to publish exactly this, in the same words
a better figure would have got.

**The model answered; it did not solve, and that distinction is checked rather than assumed.** All 55
local trials returned a non-empty patch — 43 of them begin `diff --git` and 45 carry a hunk header —
with `error = null` and `retries = 0` on every one, 83,965 input and 16,997 output tokens in total, a
median trial of 9.9 s and a longest of 124.6 s against the 900 s trial timeout, and a largest single
completion of 2,512 tokens against the 8,192-token budget. Nothing timed out, nothing errored,
nothing came back empty. **This is a zero the model earned, not a zero the wiring produced** — the
distinction §2's smoke was run in order to be able to make, now made on the suite that counts.

**The renderer declined to name a winner, on live data, for the first time.** Between `null` and
`naive-local` the report says:

> No winner: the pass^n confidence intervals overlap.
> the tools solved the same tasks; nothing to test

Both intervals are [0.000, 0.259]. That refusal is a code path with a test behind it rather than an
editorial habit, and until this run no real figures had ever reached it. **Its first live firing is
itself a result**, and what it says is the uncomfortable true thing: on this suite, at n=5, this
local model is not distinguishable from an adapter that returns nothing. A renderer willing to break
the tie would have printed an ordering the evidence does not contain. Where the intervals do
separate it did name a winner — `ground-truth` over each of the other two, with exact McNemar
p = 0.0010 printed beside it and labelled as a test of whether they differ, never of which ranks
higher.

**The stop rule binds here, and this is where it is honoured.** §1's rule was written on 2026-09-08:
whatever pass^n comes out is published as it came out, **including 0.000**, and a second model is a
new decision with its own ADR rather than a re-roll. The figure is 0.000. It is published. Nothing in
this document proposes a second model, and nothing in §1 was edited after the fact.

**What this run does not establish, restated so it cannot be read off the table.** The run names no
tool, so it is not a tool number — the local baseline is exempt from supplying one and does not
supply one
([ADR-0060](../adr/0060-the-local-baseline-is-exempt-and-does-not-discharge-the-rule.md)). The
finding is about one small model as it is served on this one machine, with one prompt and no agent
loop, on 11 tasks mined from one repository, at n=5. It is not a statement about local models, not a
statement about 7B models, and not a leaderboard row.
Which of ADR-0042's statements about this repository the run overtook, and which of its rules it left standing, is recorded in [ADR-0072](../adr/0072-a-premise-of-adr-0042-is-overtaken-and-the-rule-stands.md).
