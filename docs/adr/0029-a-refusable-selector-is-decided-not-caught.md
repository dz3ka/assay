# ADR-0029: A selector no runner would accept is decided in the miner, never caught at the seam

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Bogdan Dzekic

## Context
Both test runners refuse a selector that would reach their argv as a command-line option.
[`src/assay/host/pytest_runner.py`](../../src/assay/host/pytest_runner.py) raises `SelectorError`
and [`src/assay/sandbox/runner.py`](../../src/assay/sandbox/runner.py) raises `SandboxError`, each
before any process or container starts, and both refuse the empty string on the same terms. The
reasoning is identical and correct: a dropped selector would run a smaller suite than the gate
believes it ran, and a selector read as a flag would run a different one, so the value is refused
loudly rather than repaired.

`assay.mine.pytest_selectors` ([`src/assay/mine/candidates.py`](../../src/assay/mine/candidates.py))
is what decides which of a commit's changed test files a runner is pointed at. Its docstring already
promised "the members of `test_files` a test runner can actually be pointed at", and it kept every
path ending in `.py` — including `-x.py`. So the producer's idea of runnable was wider than the
consumer's, and the gap had a cost: a walk that met one such path would end on an `AssayError` where
it should have discarded one candidate and kept counting. Losing a walk is not losing a row. It is
losing the denominator, which CLAUDE.md calls the honest half of the result.

Two facts bound how big the hole actually is, and both matter to the shape of the fix.

Git cannot deliver one. [`src/assay/host/git.py`](../../src/assay/host/git.py) refuses a path
beginning with a dash the moment git reports it, so no mined commit and no fixture commit can carry
such a test file. A **suite on disk** can: `Task.test_files` is checked for being repo-relative
POSIX and nothing else ([`src/assay/suite/models.py`](../../src/assay/suite/models.py)), because a
published schema is API and narrowing it on a runner's behalf would be a breaking change made for a
runner a future suite may not use (ADR-0012). `assay validate` is therefore the caller that can
genuinely be handed one, and it is exactly the command whose job is to survive a bad row.

There is a second, quieter hole in the same function's contract. `pytest_selectors` has always
dropped a test-half data file such as the fixture repository's `tests/data/sample.bin`, and
`_mine_one` checks the result before running the gate — but `revalidate_suite` calls `run_gate`
**directly**, bypassing that check. A recorded task whose `test_files` hold nothing runnable
therefore reached pytest with an *empty* selection, and pytest with no selection collects the whole
repository. The gate would then have decided on a run nobody chose and reported it as that task's
own red or green: a confident number nobody should trust.

## Decision
**A selector no runner would accept is decided against in `assay.mine`'s pure layer, so that no
caller ever has to catch the runner's refusal.** Two lines, one rule.

`pytest_selectors` keeps a path only when it ends in `.py` **and** is usable as one argv entry —
non-empty, and not beginning with a dash. That is not a new moving part; it is the function
finally meaning what its own docstring said. The empty string needs no separate test here, because
it does not end in `.py`; the runners test it explicitly because they are handed selectors this
function did not produce.

`run_gate` refuses to run with an empty selection: if `pytest_selectors` returns nothing, the
outcome is `no_test_changes`, decided before a worktree is opened. It is the same discard
`_mine_one` already makes on the commit's diff, moved to the one place both callers pass through.

**This is not a retreat from [ADR-0027](0027-the-context-must-be-the-commit-the-tag-claims.md), and
0027 is not superseded.** The distinction is where the fact lives. *A selector is the task's own
data, known before any container exists, so it is decided in `assay.mine`'s pure layer; a
composition failure is a property of Assay's wiring, discovered only when the runner runs, and it
still kills the run.* ADR-0027 says the same from its own side — a mis-composed build context
is "a property of Assay's own wiring, not of the commit under test" — and
[ADR-0028](0028-a-cgroup-kill-is-the-tools-failure.md) rests on the same line. **No `SandboxError`
and no `AssayError` is caught anywhere by this change.** Both prohibitions are untouched and, by
removing the one input that would have tempted a caller to catch, reinforced.

[ADR-0025](0025-the-one-widening-is-spent.md) **confirms this, and is not amended by it.** The
spent widening is scoped to the task image's dependency install: it governs what may be installed
to make a commit measurable, not the outcome taxonomy. This change installs nothing, moves no
published number, and mints no rejection reason. The fixture yield is unchanged at 11 examined, 7
candidates, 2 accepted, and it could not have moved — no fixture commit can carry the path that
motivated the record.

## Alternatives considered
- **Catch the refusal at the `runner.run` seam.** Rejected, and it is the obvious one.
  `assay.mine` may not import `assay.host` or `assay.sandbox` (`src/assay/mine/protocols.py`, pinned
  by `tests/mine/test_package_boundary.py`), so the catch could only be spelled `except AssayError`
  — which would also swallow a `CommandFailedError` from a dead docker daemon and a `SandboxError`
  from a mis-composed runner. That is precisely the swallow ADR-0027 and ADR-0028 require to end the
  run, traded away to handle an input the miner can simply not produce.
- **A ninth `GateRejection` member, `selector_unusable`.** Rejected on the price
  `src/assay/mine/models.py` sets and [ADR-0015](0015-a-rejection-reason-must-be-reachable.md)
  established: a new reason costs a walked fixture commit that reaches it, a place on one side of
  `PRE_GATE_REJECTIONS`, and a moved expected yield with a record behind it. The first is unpayable
  here — `host/git.py` refuses the path before the miner sees it, so no fixture commit exists
  to witness the reason, and a permanent `selector_unusable: 0` in every reported yield reads as
  "this was looked for and never happened" when the truth is that the walk cannot reach it.
  `no_test_changes` is already the honest name: there is no runnable test change.
- **Count it as `unprovisioned`.** Rejected. That count is what ADR-0025 published its 125-image
  finding on, and a value that means "this workspace could not be given an environment" would start
  also meaning "this task was written down wrong". Two populations under one number is the
  unreadable tally ADR-0017 spent a milestone splitting apart.
- **Carry the refusal in a `TestReport`, the way `timed_out` is carried.** Rejected: it routes to
  `no_tests_executed`, which ADR-0017 and the M2 milestone report as evidence *about the
  repository's commits*. A malformed row in a suite file is not evidence about the repository, and
  filing it there would corrupt the one tally M2 exists to make readable.
- **Export a public `is_runnable_selector` predicate for all three sites to share.** Rejected. It
  cannot be shared where it is needed — the two runners live in packages `assay.mine` is forbidden
  to import — so a public predicate would buy one deduplication (miner and host) while leaving the
  sandbox copy where it is, and add a third public name to the miner's surface for six lines of
  rule. ADR-0012's posture applies: a constraint spelled more than once is licensed by a drift test,
  not by a shared symbol. `tests/sandbox/test_runner.py` now asserts all three spellings agree, per
  hostile path, through `pytest_selectors` and the two runners' public `run`.

## Consequences
`assay validate` now reports a task with no runnable test file as one failing row and checks the
rest of the suite: `revalidates()` is `False` for the rejection, which is the answer that command
already knows how to print. Before this record it would have ended the run on a `SelectorError`, or
— for a recorded data file — quietly revalidated against the whole repository's test suite.

The gate has a stated precondition it did not have: `run_gate` never points a runner at an empty
selection, and never at an argument either runner would refuse. `GateOutcome | None`, `MiningYield`,
`PRE_GATE_REJECTIONS` and `GATE_VERDICTS` are all unchanged, so nothing a report prints moves.

**The residue, named rather than fixed.**
[`src/assay/score/trial.py`](../../src/assay/score/trial.py)
builds a trial's selectors from `task.fail_to_pass` and `task.pass_to_pass`, which the suite schema
deliberately leaves unconstrained (ADR-0012 explains why the node-id shape is checked at the miner
and left wide at the boundary). A recorded node id beginning with a dash therefore still ends a
scoring run, exactly as an unusable `test_files` entry used to end a mining walk. It is the same
shape at a different caller and a different seam, it costs a run rather than a wrong number, and
`assay run` is M3's to own — so it is written down here rather than patched from inside M2's
package, in the posture [ADR-0026](0026-the-image-residue-is-reported-not-counted.md) set: the
residue is reported, not gold-plated away.
