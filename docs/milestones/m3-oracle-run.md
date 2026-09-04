# M3 end-to-end run: the two oracles against the fixture repository

**Run date:** 2026-09-04 · **Assay at:** M3 working tree (on `d877e31`) · **Milestone:** M3, the
`assay run` exit criterion

This run exists to answer one question: **does `assay run` produce a real result set — n trials per
task per tool, pass@1 and pass^n, Wilson intervals, winner suppression, a written result file — on
a genuine mined suite?** It answers yes.

It answers nothing at all about naive-vs-agentic. Read §2 before quoting anything from §3.

## 1. What was run

Two adapters, both oracles: **ground-truth**, which replays the known-good diff, and **null**, which
does nothing. No model was called. No API key was set. The run cost nothing.

```
uv run assay mine --repo <fixture> --out suite.json --test-timeout-s 120
uv run assay run --suite suite.json --repo <fixture> --out results.json \
  --adapter ground-truth --adapter null --trials 5 --trial-timeout-s 900
uv run assay report --results results.json
```

`_adapter_refusal` (`src/assay/cli/main.py:768-795`) exempts the two oracles from the
naive-baseline requirement, so this pair is a **designed path, not a workaround**. Its docstring
says why: the oracles answer from the task itself, so a run of the pair measures the harness and has
nothing to compare a baseline against. **No code was changed to make this run legal.**

| | |
|---|---|
| Target | SPEC §9's fixture repository, built by `tests/fixture_repo.py::build_fixture_repo` |
| Suite hash | `sha256:8159b286469af74eb57021805fc6532268a1eaac03e6bc579cf70f0d40a3b5b6` |
| Docker | server 29.7.2, one image built per task, measurement phase `--network none` |
| Trials | 2 tasks × 2 adapters × 5 trials = **20**, all recorded, exit `0` |

### The yield, stated as a yield

**11 single-parent commits examined → 2 valid tasks.** 7 candidates reached the gate, 0
unprovisioned; merges and the root commit are not examined at all. Rejected: `no_test_changes` 1,
`no_source_changes` 2, `patch_did_not_apply` 1, `already_green` 1, `still_red` 1,
`no_tests_executed` 1, `unstable_green` 1, `run_timed_out` 1.

That reproduces `tests/fixture_repo.EXPECTED_YIELD` exactly, which is the point of the fixture: all
eight rejection reasons fire, and the red→green gate is demonstrated on both sides.

**The target is a purpose-built fixture, not a real repository.** Two tasks is a suite that proves
the harness runs; it is not a suite that measures anything about software. The M2 re-mine
([`m2-yield-httpie-pinned.md`](m2-yield-httpie-pinned.md)) is the reason no real-repo suite was
available to run instead: it reached zero valid tasks on 40 httpie commits, and that blocker is
untouched by M3.

## 2. What this run does NOT buy

**No model was called during M3. There is no naive-vs-agentic comparison, and this milestone must
not be read as containing one.**

SPEC's M3 exit criteria name both real adapters. The naive baseline
(`src/assay/adapters/naive.py`) and the agentic Claude Code adapter
(`src/assay/adapters/agentic.py`) are **built, unit-tested against fakes, and container-tested** —
and **never measured live, against anything**. Every branch of both is reachable in CI on injected
seams; not one of them has answered a real model.

This was a deliberate call, not an oversight: user ruling 12 (2026-09-03) cut the paid live run from
M3 rather than spend on it. The consequence is recorded here in plain words because a project whose
entire subject is measurement honesty cannot afford to let a reader infer that the tools were
compared. **They were not.** The first live run is M4's.

Specifically, nothing in this repository yet demonstrates:

- that the naive baseline can solve any task, on any repository;
- that the agentic tool can solve any task, on any repository;
- that either beats the other, or that the agentic tool beats one raw model call;
- that the in-container `api.anthropic.com` allowlist works against the real endpoint;
- what a trial costs, in tokens or dollars.

## 3. The result

```
ground-truth  trials=10  pass@1=1.000  pass^n=1.000  pass^n interval=[0.342, 1.000]
null          trials=10  pass@1=0.000  pass^n=0.000  pass^n interval=[0.000, 0.658]

ground-truth vs null: No winner: the pass^n confidence intervals overlap.
```

**The CLAUDE.md bracket holds on real executable signal.** Ground truth is perfect on every trial of
every task; null is zero on every trial of every task. Those two numbers bracket every result any
real tool can ever produce here, and they were produced by the same code path a real tool would take
— worktree, test-patch application, image, container, test run, junit parse — not by a shortcut.

Wilson intervals are real, from `src/assay/stats/wilson.py`, computed on 2/2 and 0/2 over **tasks**
(ADR-0035). The M0 placeholder apparatus is gone.

### The renderer refused to declare a winner, and it was right to

This is the finding worth keeping. A perfect adapter and a zero adapter, and Assay **still would not
call it**, because 2 tasks is not enough for the Wilson bands to separate: `[0.342, 1.000]` overlaps
`[0.000, 0.658]`.

That is the winner-suppression code path (CLAUDE.md's "the report renderer refuses to declare a
winner when intervals overlap") firing on real data for the first time, and it fired against the
most lopsided input that will ever be handed to it. A harness that would announce a winner here
would announce one anywhere.

It is also an honest bound on this run: **a 2-task suite cannot support a ranking, and Assay says
so out loud instead of printing a number.** Widening the suite is M4's problem, and it is the same
problem as M2's zero yield.

## 4. Open flags carried into M4

Recorded so they are not rediscovered as surprises:

- `src/assay/host/model_api.py` never reads `model` back off the response — it validates `content`
  and `usage` and never touches `model`. A result set therefore proves which **alias** was
  requested, not which snapshot served. Free to fix, fake-testable, and it matters the moment
  anyone does a live run. Rejecting a dated snapshot also concedes ground to ADR-0007's
  reproducibility promise.
- `--network bridge` on the adapter phase is not a hostname allowlist. The measurement phase's
  `--network none` is exact; the adapter phase's egress restriction is not.
- `AGENT_TOOL_VERSION` is `None`; agentic attempts record zero tokens, zero tool calls and no
  `cost_usd`. A timed-out tool is not recorded as an error.
- `TRIAL_LIMITS`, `IMAGE_BUILD_TIMEOUT_S` and `DEFAULT_TRIAL_TIMEOUT_S` are unverified guesses.
- A failure at trial 400 of 500 discards the whole run: there is no resume or append.
- The M2 reach limit is unlifted. No real repository has yet produced a suite worth running.

## 5. Reproducing this

1. `uv run python -c "from tests.fixture_repo import build_fixture_repo; from pathlib import Path; print(build_fixture_repo(Path('build')))"`
2. Mine and run with the two commands in §1, against the printed path.
3. Docker must be up; the run builds one image per task.

The suite hash in §1 pins the task set. A result set from a different hash is not comparable to this
one, which is what ADR-0007 bought.
