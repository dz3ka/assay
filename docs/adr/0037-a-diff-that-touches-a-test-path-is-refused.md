# ADR-0037: A diff touching a test path is refused before it is applied, and scores `FAILED`

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Bogdan Dzekic

## Context
M3 is the first milestone in which a diff is written by a model. Everything scored until now
came from an oracle: `GroundTruthAdapter` replays a diff a real commit already contained, and
`NullAdapter` produces the empty string. Neither can do anything a mined task did not already
authorise, so nothing in the scorer has ever had to ask where a diff came from.

The tests are the measurement. A task exists because its recorded ids provably fail at the base
state and provably pass once the ground-truth diff is applied (SPEC §3), and the whole ranking
rests on those ids and nothing else (ADR-0003). A diff that edits the failing test therefore
does not answer the question — it replaces it, and the harness would then be scoring a tool
against a suite that tool wrote. The result is a `PASSED` that means nothing, which is the
precise failure CLAUDE.md names as worse than having no harness at all.

This is not a hypothesis about malice. An agent handed a repository, write access and an
instruction to make a failing test pass will weaken an assertion when it cannot find the fix;
it is the cheapest reachable green, and several published agent traces do exactly this. Nothing
in the tree stops it today. `_measure` applied whatever the attempt carried, and every one of a
tool's edits reached the runner.

What counts as a test path has two candidate answers and each one misses what the other
catches. The task's own `test_files` is exact — it is the list the miner recorded for that
commit — and narrow: it names the files *that commit* changed and nothing else. So a new root
`conftest.py`, a `pytest.ini` written under `tests/`, an edit to a different test module that
the recorded ids happen to import, and a rename of a source file onto a test path all sit
outside it while changing what a run of those ids means. `is_test_path`
([`src/assay/mine/candidates.py`](../../src/assay/mine/candidates.py)) is the other answer:
pytest's discovery convention plus any path under a `test`/`tests` directory (ADR-0032). It is
conventional rather than exact, and it is the rule the miner already used to decide which half
of the commit was the test half.

That last fact is what makes the rule affordable. `split_changes` puts every path
`is_test_path` accepts into the test half, so a task's `ground_truth_patch` is the complement
of a superset of what this rule refuses. The oracle satisfies the guard **by construction**,
not by luck, and the existing 1.0/0.0 bracket in
[`tests/score/test_end_to_end.py`](../../tests/score/test_end_to_end.py) is the standing
regression test for that claim.

## Decision
**A diff naming a test path is refused before it is applied and the trial scores `FAILED`. A
test path is `is_test_path`'s rule united with the task's declared `test_files`, and the check
is the first statement of `_measure` in
[`src/assay/score/trial.py`](../../src/assay/score/trial.py), so no runner is made and no
container is started.**

One statement, in the one place every adapter's diff passes through. The refusal returns the
same `None` that a diff which will not apply returns, which `score_report` already scores
`FAILED`; nothing new was added to the verdict vocabulary to carry it.

`FAILED` rather than `ERRORED` because the tool ran and produced an answer, and the answer is
wrong. `ERRORED` means the tool or the harness failed to run at all (ADR-0031), and a trial
that reached this branch is neither — reading it as a malfunction would move a tool's own
behaviour out of the finding and into Assay's error rate.

The rule that reads the diff is pure and total: it answers for every string and raises for
none, because a trial lost to an exception is a hole in the denominator this project reports as
the honest half of any result. It reads only the lines of a unified diff that *name* paths —
the two file headers, and git's rename and copy pairs, which are how a file moves without any
content header at all. Where a diff is genuinely ambiguous, the reading that refuses wins: a
false refusal costs one trial scored `FAILED` and stays legible in the recorded attempt, while
a false acceptance mints a confident `PASSED`. That is the direction ADR-0032 already argued is
the cheap one, and its invitation to narrow the directory rule in M3 is therefore **not**
taken — narrowing would move error into the expensive direction to buy candidates the miner
does not currently lack.

## Alternatives considered
- **Guard inside each adapter, where the diff is produced.** Rejected. It is two guards today
  and three the moment a third adapter is written, and the one that silently omits it is not
  visibly different from the ones that have it. The scorer is the only place the property can
  be stated once for every present and future adapter.
- **Refuse only the task's declared `test_files`.** Rejected. It is the exact list and it is
  the wrong exact list: a new root `conftest.py` changes collection for the recorded ids
  without appearing in it, and so does a `pytest.ini` under `tests/`. The declared list stays
  in the union because it is the only thing that knows about a repository whose tests live
  where no convention would look.
- **Apply the diff, then ask git which paths changed.** Rejected, and it is the shape that
  looks most natural. The task's test patch is applied unstaged, so a diff of the workspace
  against its checkout is non-empty on *every* trial, tampering or not, and the guard could not
  tell setup from sabotage without staging the test patch — a widening of the `History` seam
  that the miner, its only other caller, has no use for.
- **Strip the offending hunks and apply the rest.** Rejected. The result is a patch no tool
  wrote, scored as though a tool had written it. Assay would be reporting a number about its
  own editing.
- **Record it in the schema — a `tampered` flag on `Result`, or a new `Outcome` member.**
  Rejected. It is a `result_set` v2 migration and a widening of a closed set (ADR-0015's bar)
  for a fact the recorded `Attempt.diff` already carries in full, in the artefact a human
  reads.
- **Make the test files unwritable while the tool works.** Rejected as the wrong layer. It
  needs per-path permissions inside an environment the tool controls, it fails differently on
  every platform, and it answers a question a static read of the produced diff answers exactly.

## Consequences
Every adapter inherits the rule and none can opt out of it, including the agentic adapter M3
has not written yet. That is the point of the placement, and it is also the thing to keep true:
a future `_measure` that grows a second early return above this one would silently move the
guard.

A legitimate diff that *adds* a test file is refused. This is deliberate and worth stating
plainly: the trial's verdict is the recorded `fail_to_pass` and `pass_to_pass` ids, and no
added test can help those pass, so the only thing a new test file can change about a trial is
collection. Losing that trial is the cheap error.

The refusal is legible rather than silent. The attempt is recorded whole — its diff included —
so a run whose pass rate collapsed to the null adapter's floor can be read back to see that a
tool spent five trials rewriting the suite. That legibility is what ADR-0038's harvest is for:
the edit shows up in the recorded diff rather than being excluded from it.

The claim that the oracle satisfies this guard by construction is now load-bearing, so it is
checked in two places rather than assumed: the end-to-end bracket measures 1.0 for the ground
truth adapter against real git and real containers, and a unit test drives `split_changes` over
a mixed path list and runs the resulting ground-truth diff through a trial. If the split's rule
and the guard's rule ever diverge, the oracle stops scoring 1.0 and both tests say so.
