# ADR-0032: A path under a test directory is a test change, and the yield names what the rule admits

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Bogdan Dzekic

## Context
`is_test_path` in [`src/assay/mine/candidates.py`](../../src/assay/mine/candidates.py) decides which
of a commit's changed paths belong to its test half. The rule has three clauses: a path carrying a
`test` or `tests` directory segment, pytest's own module-naming convention (`test_*.py` and
`*_test.py`), and `conftest.py`. What it does not claim, `split_changes` hands to the ground truth,
so the split is **total by construction** — a path claimed by neither half would disappear from both
patches, and the gate would be measuring a diff nobody ever reviewed.

M2's wrap review put the directory clause under the light. It is wider than its name sounds. Take a
commit that changes a production module and, in the same commit, a helper that happens to live under
`tests/` — a fixture factory, a shared assertion library, a builder — and no file pytest would ever
pick up as a test. It has a non-empty test half and a non-empty ground-truth half, so `_mine_one`
sends it to the gate and the rendered yield line counts it under **candidates**: "N single-parent
commits examined -> A valid tasks, C candidates reached the gate". A reader takes `candidates` to
mean *commits that are test-anchored fixes*. Under this rule it means *commits whose changed paths
include something the rule calls a test change*, and those are not the same set.

The rule is already narrowed once, downstream, and that is what makes the gap precise rather than
vague. `pytest_selectors` keeps only the members of the test half a runner can be pointed at, which
drops the fixture repository's own `tests/data/sample.bin` — a file the directory clause admits and
pytest could never collect ([ADR-0029](0029-a-refusable-selector-is-decided-not-caught.md) records
the second half of that filter). A helper module survives it, because the property that filter tests
is *runnable-looking*, and a factory module under `tests/` ends in `.py` exactly as every real test
file does. What the review is asking for is therefore not one more clause over the path string. It
is the difference between a module pytest collects tests from and a module it does not, and a path
does not carry that fact.

## Decision
**The directory clause stays exactly as it is for M2. The limitation is recorded in the yield's own
terms, and any narrowing is deferred to M3.** `is_test_path`, `pytest_selectors` and `split_changes`
are unchanged, no rejection reason is minted, the fixture repository's expected yield of 11 examined,
7 candidates and 2 accepted is untouched, and no number a report prints moves. Two grounds carry it.

**The rule is deliberately conservative in one direction only, and the two directions cost different
things.** A source file misread as a test would be applied *before* the gate's red run, as part of
the test patch, and could make a genuinely red commit look already green — a wrong task minted, or a
real one lost under `already_green` for a reason that is about Assay rather than about the commit. A
test file misread as source costs the candidate and nothing else: it is discarded as
`no_test_changes` and counted there. `is_test_path`'s own docstring already states that asymmetry,
and it is the standing posture of `decide_gate`, which discards every shape of evidence it does not
recognise. **Losing a candidate is the smaller error than minting a wrong one**, and a narrowing made
with no measurement behind it trades the smaller error for the larger one.

**The red-to-green gate is the real filter, and it already resolves this commit.** Follow the
helper-only candidate through: the test patch applies, the runner is pointed at the helper module,
and pytest collects nothing from it. The red run is silent, which `decide_gate` accepts as a failure
shown — a selection that ran nothing is one of the three shapes SPEC §3 step 3 counts. The
confirmation runs are silent in the same way, so they are not green, and both ends being silent is
exactly the split [ADR-0017](0017-still-red-stays-merged-until-m2-pins-the-environment.md) carved
out: the commit is discarded as `no_tests_executed`. If instead the helper edit breaks an import,
both ends report the same uncollectable file and the discard is `still_red`. **There is no path
through the gate on which such a commit becomes a task** — nothing can cross from red to green when
nothing is collected — and either way the discard is counted, under a reason already reachable.

So the over-wide clause costs **precision in the yield's denominator, not validity in the tasks that
survive it**. That is a real cost and it is the one being recorded rather than waved away: the
denominator is doing work in every yield this project publishes.

## Alternatives considered
- **Narrow the rule to files pytest would collect, dropping the directory segment.** Rejected, and
  it is the direct reading of the review finding. The directory clause is not decoration: it is what
  carries a test patch's *data* — the binary fixture the fixture repository's `payload_format_two`
  commit edits, a golden file, a `conftest.py` in a subdirectory — into the test half, where the
  patch applied before the red run can reach it. Drop it and those files land in the ground-truth
  half, so the applied test patch would reference data the workspace does not have and a genuinely
  valid task would fail the gate for a reason the classifier invented. That converts a precision
  problem in the denominator into wrong verdicts in the numerator, which is the trade CLAUDE.md's
  measurement rules exist to refuse.
- **Classify by whether a file is reachable from a collected test.** Rejected as a measurement the
  miner is not allowed to take. It answers the question correctly, and it can only be answered by
  importing or executing the repository under evaluation at mine time — collecting its suite,
  resolving its imports — for **every** commit, before any decision about whether that commit is a
  candidate at all. Mining's split is a pure function over the paths git already reported
  ([ADR-0002](0002-tasks-are-mined-not-authored.md) and CLAUDE.md's code conventions both put it
  there), and [ADR-0013](0013-mining-runs-on-the-host-in-m1.md) is this project's record of how
  narrowly it is willing to run a target repository's code at all. Running a stranger's collection
  to decide a path's category is a far larger exposure than the one 0013 accepted, bought for a
  count.
- **Mint a `GateRejection` member for "the test half is only helpers".** Rejected on the posture
  [ADR-0026](0026-the-image-residue-is-reported-not-counted.md) set and
  [ADR-0015](0015-a-rejection-reason-must-be-reachable.md) established: residue is reported in prose
  rather than minted as a further rejection reason, and a member has to be reachable by a walk that
  can tell that reason apart from its neighbours. This one cannot be. Deciding "only helpers" *is*
  the collection measurement the previous alternative rejects, so the member could only ever be
  assigned from a fact the miner does not have — while the gate already resolves these commits into
  `no_tests_executed` and `still_red`, both of which have walked fixture witnesses today.

## Consequences
**`candidates` means "commits whose changed paths include a test change under this rule", not
"commits that are test-anchored fixes", and no report may claim the latter.** That is a
documentation obligation on M2's milestone write-up and on anything M3 renders from a `MiningYield`.
The yield line already names its other two subtleties in words — merges and the root commit are not
examined, and `unprovisioned` sits outside the reason set — and this is the third thing the number
does not say about itself.

Everything the clause admits and the gate then rejects **is counted as a discard**, which is the
honest form and the reason the cost stops at precision. A reader who sees `no_tests_executed` rise
on a repository that keeps a large helper library under `tests/` is seeing this rule, and the count
is where they will see it.

**The tally does not separate the two populations now sharing `no_tests_executed`**, and that is
named here rather than fixed: a candidate whose test half collected nothing because it held only
helpers sits beside one whose tests were silenced by the environment built for them, which is the
distinction ADR-0017 split `still_red` apart for in the first place. Splitting it again needs the
same thing a narrowing needs — a measurement — so it waits on the same evidence.

**M3 may narrow the rule once there is a measurement that justifies a specific narrowing.** What
that would take is written down here so the next milestone does not have to rediscover it: a count
of how many candidates on a real repository have a helper-only test half, a walked fixture commit
that witnesses the shape, and a decision about where the collection fact is permitted to come from.
Narrowing now would be tuning a classifier against no data, on a repository whose numbers this
project has already declined to publish.
