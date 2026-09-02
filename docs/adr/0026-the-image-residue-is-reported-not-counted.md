# ADR-0026: The task image's residue is reported in prose, not minted as a ninth rejection reason

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Bogdan Dzekic

## Context
The post-fix re-mine ([`docs/milestones/m2-yield-httpie-pinned.md`](../milestones/m2-yield-httpie-pinned.md))
left five things the task image cannot do: it cannot restore a yanked release, it cannot pin the
interpreter to the commit's era, it cannot install an undeclared system package or start a service
for a test that needs one, it cannot install an extra named outside the four-name allowlist, and it
cannot promise that `host/junit.py`'s shapes — calibrated against pytest 9.1.1 — hold for every era
of pytest an epoch-pinned image might install.

Each of those makes a commit fail in a way that is *not* what the tally says. The first two produce
a build failure, currently counted `unprovisioned`. The third produces a red run indistinguishable
from a fix that did not work. The fourth reproduces ADR-0019's original blocker for a repository
that spells its test extra `ci`. The fifth would produce a misparsed report and therefore a wrong
verdict, silently.

The obvious response is to make the tally say it: a ninth `GateRejection` member — some
`environment_unbuildable`, or a `no_tests_collected` distinct from `no_tests_executed` — so a
reader can see the residue in the numbers instead of in a paragraph. That is exactly the move
[ADR-0015](0015-a-rejection-reason-must-be-reachable.md) exists to stop, and the reasoning that
killed `merge_commit` and `ENVIRONMENT_FAILED` applies here without modification:

> A rejection reason must be reachable by the walk, demonstrated by a walked fixture commit that
> actually lands on it.

No such fixture commit can be built for any of the five. `tests/fixture_repo.py` constructs its
repository with every object name pinned and no dependency on an index at all: a commit that lands
on "the era's index had no wheel for this interpreter" would need the fixture to declare a real,
dated, external dependency, which would make eleven pinned shas hostage to PyPI and to the day the
suite runs. A commit that lands on "the test needed a database" would need the fixture to *have* a
database. The witness cannot exist, so under ADR-0015 the member cannot exist either.

## Decision
**The residue is reported, and it is not counted as a rejection.** Concretely:

A commit whose image cannot be built stays `unprovisioned` — a count that sits *beside* the
rejection set rather than inside it, because the gate never spoke about that commit. `MiningYield`
already carries it and `_check_partition` already balances it against `commits_examined`, so the
partition stays honest without a new member: `accepted + sum(rejected) + unprovisioned` is the
whole examined set, and a reader who sees `unprovisioned` rise knows the walk lost commits before
the gate rather than at it.

Everything the count cannot name is named **in the milestone document, in prose, with the mechanism
spelled out** — which is where a reader can be told the difference between "this test needed
PostgreSQL" and "this fix did not work", a difference no enum member can carry. The eight-member
set closes at eight for M2.

`GateRejection` is unchanged; `PRE_GATE_REJECTIONS` and `GATE_VERDICTS` are unchanged;
`MiningYield._check_partition` is unchanged; the fixture repository's pinned object
names and its expected yield are unchanged. [ADR-0006](0006-network-off-inside-a-trial.md),
[ADR-0013](0013-mining-runs-on-the-host-in-m1.md), ADR-0015 and
[ADR-0017](0017-still-red-stays-merged-until-m2-pins-the-environment.md) are all untouched by this
record — in particular ADR-0017's split, which M2 did carry out because a fixture commit *could*
reach `no_tests_executed` and does.

## Alternatives considered
- **Add a ninth member for the unbuildable image.** Rejected on ADR-0015's witness rule. It would
  also be a category error: the reasons are verdicts of the red→green gate, and a commit whose
  image never built never reached the gate. Putting it in the same set would let a reader add two
  numbers that are not about the same question.
- **Give `unprovisioned` a reason breakdown — a mapping instead of an integer.** Rejected as the
  same decision wearing different types. Every key would still need a witness, and the schema
  change would be permanent (`MiningYield` is a versioned document) in exchange for a distinction
  only the milestone prose can actually draw. If M3's pinned-image `mine` finds it needs one, it
  can be argued for then, with the run that motivates it in hand.
- **Relax the witness rule to "reachable in principle".** Rejected, and it is the tempting one,
  because "in principle" is how `merge_commit` and `ENVIRONMENT_FAILED` got in the first time. A
  reason nothing can reach is a reason nothing tests, and the first time it is *wrong* is the first
  time a real repository lands on it — in a published number.
- **Build a fixture that declares a real external dependency, so an era failure has a witness.**
  Rejected: it would make the fixture's eleven pinned object names, which are the cross-platform
  canary between the Windows dev host and Linux CI, depend on an index and on the calendar. The
  fixture's whole value is that it is hermetic.
- **Say nothing, and let the residue show up as a lower yield.** Rejected outright. That is a
  harness producing a confident number nobody should trust, which CLAUDE.md calls worse than no
  harness. The yield is reported with its denominator, and what the denominator hides is written
  next to it.

## Consequences
A reader of a yield table can see how many commits were lost before the gate, but not why any
particular one was — that answer lives in the run's log and in the milestone document, and it is a
deliberate cost of keeping the reason set honest.

`read_installed_closure` carries part of the load an enum member would have carried badly: an image
that built has a recorded closure, so "the environment drifted" is checkable after the fact instead
of being guessed at from a verdict. That is reporting, not counting, and it is the shape the rest of
the residue should follow.

M3 inherits two named triggers rather than an open question, and the first has **already fired**:
the full httpie walk lost 125 of 743 commits — 124 of 126 attempted images — to unbuildable
environments. Under this record that shows up as `unprovisioned` climbing and the rejection set
staying still, which is the correct shape: the walk lost those commits before the gate. The
decision it reopens is "per-era base images", not "a ninth reason". And if an era of pytest ever writes a junit shape
`host/junit.py` misreads, that is a calibration finding with its own record — the shapes are
measured facts in a docstring, and the honest response to a new measurement is a new measurement.
