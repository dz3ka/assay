# ADR-0017: `still_red` conflates "the fix did not work" with "no test ran", and stays merged until M2

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Bogdan Dzekic

## Context
`GateRejection.STILL_RED` is returned when the confirmation runs are not green
([`gate.py:92`](../../src/assay/mine/gate.py)). `_shows_failure` (`gate.py:144`) counts three shapes
as red — "a test that failed, a file that would not collect, or a selection that ran nothing at
all" — and `_is_green` (`gate.py:157`) demands a clean exit code on top of the statuses. Both are
deliberately conservative, and both are correct.

The by-hand httpie run ([`docs/milestones/m1-yield-httpie.md`](../milestones/m1-yield-httpie.md))
showed what that costs on a real history: 743 commits examined → **0 valid tasks**, 171 at the
gate, `no_test_changes` 572, `still_red` 127, `no_source_changes` 44, every other reason 0. The 127
were investigated rather than assumed, and they are uniform:
**on not one of them did a test ever execute.** `tests/conftest.py` died on
`ModuleNotFoundError: No module named 'pytest_httpbin'`, so pytest exited **4 — a usage error, with
zero statuses and an empty `uncollectable` set** — identically at parent and fixed state. The
conftest dies before any test file is reached, so this is not a collect error and the
`COLLECT_ERROR` vocabulary is not what it turns on; it is `exit_code in _NOTHING_RAN and not
statuses`. `_shows_failure` reads that as red, rightly; `_is_green` refuses a non-zero exit,
rightly. **The gate is correct; its evidence is not.**

So one tally carries two claims a reader cannot pull apart: *the fix did not make its tests pass*,
a statement about the repository's history, and *no test ran in either state*, a statement about
the environment Assay built. The bucket holds a third by construction — an empty `fail_to_pass`
(`gate.py:105`), the failing test deleted rather than fixed — but that is at least a fact about the
commit. The environment case is not, and 127 of 127 were it.

## Decision
**The bucket stays merged for M1**; no `no_tests_executed` member is added now. The distortion is
named in words instead — in the milestone document, which states that this run's `still_red` count
is an environment artifact, and here.

The split is **deferred to M2 with a named trigger**: M2's pinned per-task images (SPEC §5.2,
[ADR-0019](0019-m1-cannot-mine-unpinned-test-dependencies.md)) remove the environment cause, after
which a residual `still_red` means what it says and the split separates two populations that both
really occur, rather than a real one from a defect. Splitting first would build vocabulary on top
of a bug and let the bug read as taxonomy.

The cost is stated rather than absorbed: while merged, **a `still_red` tally cannot distinguish a
real negative from an environment failure, and must not be read as evidence about the repository's
history.** Any run reporting a non-trivial `still_red` share owes its reader that sentence, and the
httpie document carries it.

## Alternatives considered
- **Add `GateRejection.NO_TESTS_EXECUTED` now.** The genuine contender.
  [ADR-0015](0015-a-rejection-reason-must-be-reachable.md) requires every member to have a walked
  fixture commit that reaches it, and — unlike `ENVIRONMENT_FAILED` — **a witness is constructible
  without the network**: a fixture commit whose `conftest.py` imports a module that does not exist
  produces exactly the exit-4, no-statuses shape. The ground for rejecting it is therefore **scope
  and sequencing, not impossibility** — saying otherwise would overstate the cost the way ADR-0015
  warns against. It changes `GateRejection`, which the report schema is versioned on, inside a
  finished milestone, to name a population M2 is about to eliminate.
- **Report the two populations as a count beside the reason set,** the way `unprovisioned` is —
  ADR-0015's second rule, and the closest alternative here. What tips it is that this population
  is not "examined but unjudged": the gate *did* speak, and defensibly. A count beside the reasons
  would break the partition's meaning (accepted + rejected + unprovisioned = examined) to describe
  a *quality* of one reason's evidence — a different kind of fact, which belongs in the run's prose
  while its cause is a known defect.
- **Widen `_is_green` to accept exit 4, or stop counting "ran nothing" as red.** Rejected outright:
  it manufactures tasks from runs that proved nothing, the one direction a threshold here may never
  move.
- **Leave it undocumented and let the tally speak.** Rejected on CLAUDE.md's terms: a number that
  is true and misleading is the failure this project exists to catch.

## Consequences
`still_red` remains the honest verdict on the evidence and a poor summary of the world, and any
report quoting it carries the caveat until M2 lands. The trigger is explicit, so the split is a
scheduled decision rather than a note someone may rediscover — and the witness commit that would
make `NO_TESTS_EXECUTED` reachable is designed here, so M2's work is to build it and re-derive
SPEC §9's expected yield around it, not to re-argue whether the reason can exist.
