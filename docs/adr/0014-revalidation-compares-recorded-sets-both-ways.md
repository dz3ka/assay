# ADR-0014: Revalidation is strict in both directions, and the yield partition lives in the model

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Bogdan Dzekic

## Context
Two accounting rules were found half-written in the same review of M1's mining pipeline, and they
fail the same way: the code was right for the run that produced the number and silent about the
document read back afterwards.

The first is `assay validate`. Re-running the gate over an existing suite produces a fresh
`GateOutcome`, and the tempting test is "did it accept?". It is not enough.
[`decide_gate`](../../src/assay/mine/gate.py) accepts on whatever crosses red to green **now**,
which need not be what the suite wrote down: a dependency update that makes one recorded
`fail_to_pass` test pass at the base state, while another test from the same patch still crosses,
is an acceptance with a different set. Scoring afterwards gates on the *task's* sets, so blessing
that task leaves a suite whose null adapter can pass — and the null adapter scoring zero is a
CLAUDE.md non-negotiable.

The second is `MiningYield`. Its identities — every reason present, no negative counts, accepted +
rejected + unprovisioned = examined, every candidate judged by the gate — were checked inside
`tally_yield`, the function that counts. A yield is also *parsable*, and that is the half a
counting-time check does not cover. Nothing in M1 carries one into a suite file yet - `SuiteFile`
records only the schema version, hash, timestamp, generator and body - but the identities have to
survive a yield being read back by a report that never ran the miner.

## Decision
**Revalidation reproduces both recorded sets, and is strict in both directions.**
[`revalidates(task, outcome)`](../../src/assay/mine/gate.py) compares `fail_to_pass` and
`pass_to_pass` as sets against what the task records; an outcome that is `None` (no environment
could be provisioned) is not valid either, because a suite that could not be re-proved has not
been re-proved.

**A suite that *under*-records `pass_to_pass` is invalid too**, and that is the decision rather
than an oversight — the direction a reader will assume was forgotten is the one deliberately
included. A task file is a claim about the run that will score it. If the gate now proves more
than the task says, the file and the run disagree, and the disagreement is invisible at scoring
time because scoring reads the file. `validate` answers "does this suite still describe reality",
not "is reality at least as good as this suite".

**The partition is enforced by the model, not by the counter.**
[`MiningYield._check_partition`](../../src/assay/mine/models.py) holds all four clauses, so a
yield read back from a file is refusable on exactly the terms one counted in process is.

## Alternatives considered
- **Require only that the recorded `fail_to_pass` still crosses.** Rejected: it accepts silent
  erosion of `pass_to_pass` — a regression guard the suite claims and no longer has.
- **Be strict about over-recording, lenient about under-recording.** Rejected: an asymmetric rule
  needs a reason for the asymmetry and there is none. Both directions are the file disagreeing
  with the run, and re-mining is the remedy for both — which content addressing wants anyway,
  since a task with different sets is a different document with a different digest.
- **Keep the identities in `tally_yield` only.** Rejected, and this is the sharper half: it is
  precisely [ADR-0011](0011-string-constraints-live-on-the-schema.md)'s rejected "escape once in a
  shared helper every renderer calls", applied to arithmetic instead of to strings. It holds only
  while every producer routes through the helper, and nothing in the type system says one must.
- **Keep the nesting inequalities (`candidates <= commits_examined`, `accepted <= candidates`) as
  well.** Rejected as implied by the two equality clauses — but only because the no-negative-count
  clause is there too. `Field(ge=0)` constrains the scalars and says nothing about `rejected`'s
  values, and a negative count is exactly what would satisfy both equalities while overstating
  `accepted`.

## Consequences
`assay validate` exits 1 on a suite whose sets have drifted either way, and the CLI names which of
the three ways it failed — including "the gate accepted a different set of tests", the failure a
bare verdict would hide. A dependency bump that legitimately turns a `fail_to_pass` green makes
the suite invalid rather than quietly narrower; re-mining is the answer, not editing the file.

Every `MiningYield` — including the hand-built ones in tests and the fixture oracle — must now
name all seven reasons, zeros included. `unprovisioned` carries a default of `0` so a yield
written before the field existed still parses and still describes the same partition.
