# ADR-0015: A rejection reason must be reachable by the walk; merges are excluded, not rejected

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Bogdan Dzekic

## Context
`GateRejection` is the closed set of reasons a candidate commit did not become a task, and every
discard is counted under one of them, because a yield line is a partition of what was examined
(CLAUDE.md, "report yield, not just totals"). It shipped with a `merge_commit` member.

Nothing could ever be counted under it. [`GitHistory.commits`](../../src/assay/host/git.py) asks
git for `--no-merges` and drops any record that does not arrive with exactly one parent, so a
merge — and the root commit — is never handed to the miner at all. The member was therefore a
permanent `merge_commit: 0` in every reported yield, and a zero in a table of counts is read as a
measurement: *merges were examined and none was rejected*. The truth is that none was looked at.
That is not a cosmetic difference; it is the denominator, which is the honest half of the result.

The same shape then arrived a second time. A commit whose workspace cannot be given an environment
its tests could run in — `provision_venv` fails, `RunnerFactory` returns `None` — was walked, so
it *was* examined, but the gate never spoke about it, so it is not a candidate and no reason
describes it.

## Decision
**A `GateRejection` member must be reachable by the walk**: there has to exist a commit the walk
yields that gets that reason. `merge_commit` is deleted. Merges and the root commit sit **outside**
the accounting rather than inside it as a reason, and the yield line says so in words — "merges
and the root commit are not examined at all" — so the reader is told about the exclusion instead
of inferring it from an unexplained denominator.

**A population that is examined but unjudged gets a named count beside the reason set, never a new
reason.** [`MiningYield.unprovisioned`](../../src/assay/mine/models.py) is that count, and it is
this rule's second application. The partition is then accepted + rejected + unprovisioned =
examined, with every reason present and zeros included: "this reason never fired" and "this reason
was not looked for" must not be the same document.

## Alternatives considered
- **Keep `merge_commit` and let it read zero forever.** Rejected: see the Context. It is the
  failure mode this project cannot afford, in miniature — a number that is true and misleading.
- **Exclude merges silently and count nothing.** Rejected: nine examined against an eleven-commit
  history is a gap a reader is owed an explanation for, so the exclusion is named in the output.
- **An eighth reason, `GateRejection.ENVIRONMENT_FAILED`, for the unprovisioned population.**
  Rejected on **one** ground: no honest witness exists. Every member is required to have a walked
  fixture commit behind it (`test_every_rejection_reason_has_a_commit_that_reaches_it`), and the
  only true witness for a failed `uv pip install` would put a network-dependent install into CI.
  A stub factory returning `None` witnesses the plumbing, not a commit that genuinely cannot be
  provisioned.

  The cost claim stops there, deliberately. An eighth member would **not** have moved SPEC §9's
  expected yield of 9 / 6 / 2: `EXPECTED_YIELD` is derived from the `FIXTURE_COMMITS` table and
  `rejected` is dense over the enum, so a member with no witness adds a zero entry and leaves the
  three counts untouched — the only test it breaks is the witness test. That was checked rather
  than assumed. An ADR that overstates the cost of a rejected alternative is the same failure as a
  report that overstates a result, so the reason is recorded at its true size.
- **Fold the unprovisioned commits into `commits_examined` without naming them.** Rejected: it
  inflates the denominator with commits nothing was learned about, and `_check_partition` refuses
  the arithmetic anyway.

## Consequences
The enum is closed at seven and each member has a fixture commit that reaches it. Adding an eighth
means building a commit that gets there; if that cannot be done, what has been found is a
population, not a reason — name it beside the counts, as `unprovisioned` is named.

The yield became three printed lines rather than one, because it is three claims. The rule is
cited from the walk, the models, the pipeline and the fixture oracle, so the next person to reach
for a new reason meets it where they are working rather than only here.
