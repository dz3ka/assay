# Architecture Decision Records

Each ADR captures one decision a competent reviewer would ask "why?" about:
the context, the choice, the alternatives weighed, and the consequences. ADRs
are immutable once accepted — to change a decision, add a new ADR that
**supersedes** the old one (and mark the old one Superseded).

Numbering is sequential at creation (`NNNN-kebab-title.md`). Status is one of:
`Proposed` · `Accepted` · `Superseded by ADR-XXXX` · `Deprecated`.

> Note: `SPEC.md` §8 lists seven decisions to record, and they are ADRs 0001–0007
> here in that order. ADRs 0008 and later are decisions M0's implementation forced
> that §8 did not anticipate. A decision the spec sketches but no milestone has
> reached yet takes its number when the code forces it, not before.

An ADR describes the tree as it stands. Where a decision binds a milestone that is
not built, it says so as a deferral and names the milestone — an ADR that reads as a
capability the code does not have is a defect, not a roadmap.

## Template

```markdown
# ADR-NNNN: <title>

- **Status:** Accepted
- **Date:** YYYY-MM-DD
- **Deciders:** <who>

## Context
<the forces at play: requirements, constraints, what makes this non-obvious>

## Decision
<the choice, stated plainly>

## Alternatives considered
<each rejected option and why it lost>

## Consequences
<what becomes easier, what becomes harder, follow-ups triggered>
```

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-python-3-12-managed-with-uv.md) | Assay is Python 3.12 managed with `uv`, not TypeScript | Accepted |
| [0002](0002-tasks-are-mined-not-authored.md) | Tasks are mined from git history, not authored | Accepted |
| [0003](0003-rank-only-on-executable-signal.md) | Ranking reads executable signal only; judges inform and never rank | Accepted |
| [0004](0004-pass-caret-n-is-the-headline-metric.md) | pass^n is the headline metric; pass@1 is reported for comparability | Accepted |
| [0005](0005-no-winner-when-intervals-overlap.md) | Overlapping intervals declare no winner, and the schema refuses to say otherwise | Accepted |
| [0006](0006-network-off-inside-a-trial.md) | Network is off inside a trial; dependencies are baked into the task image | Accepted |
| [0007](0007-suites-are-content-addressed-and-versioned.md) | Suites are content-addressed and versioned, and a result cites the digest it was measured on | Accepted |
| [0008](0008-pydantic-v2-over-canonical-json.md) | Data contracts are pydantic v2 models over canonical JSON, addressed with SHA-256 | Accepted · underpins 0007 |
| [0009](0009-redaction-is-hmac-with-a-per-render-salt.md) | Redaction is HMAC-SHA-256 under a per-render salt that is never persisted | Accepted |
| [0010](0010-money-is-a-decimal-at-six-decimal-places.md) | Money is a `Decimal` at exactly six decimal places, and any other scale is refused | Accepted · applies 0008 |
| [0011](0011-string-constraints-live-on-the-schema.md) | String constraints live on the schema, not in the renderers | Accepted · widens 0005 |
| [0012](0012-the-task-id-pattern-is-spelled-twice.md) | The mined-task-id pattern is spelled twice, and a drift test licenses it | Accepted · applies 0011 |
| [0013](0013-mining-runs-on-the-host-in-m1.md) | Mining runs the target repository on the host, and M1 accepts the exposure | Accepted |
| [0014](0014-revalidation-compares-recorded-sets-both-ways.md) | Revalidation is strict in both directions, and the yield partition lives in the model | Accepted · applies 0011 |
| [0015](0015-a-rejection-reason-must-be-reachable.md) | A rejection reason must be reachable by the walk; merges are excluded, not rejected | Accepted |
| [0016](0016-a-below-floor-test-timeout-is-refused-not-floored.md) | A below-floor `--test-timeout-s` is refused at the argument surface, not floored silently | Accepted · applies 0007 |
| [0017](0017-still-red-stays-merged-until-m2-pins-the-environment.md) | `still_red` conflates "the fix did not work" with "no test ran", and stays merged until M2 | Accepted · applies 0015 |
| [0018](0018-provisioning-installs-the-runtime-set-and-pytest.md) | Provisioning installs the project's runtime set plus pytest, and no extras or groups | Accepted · applies 0013 |
| [0019](0019-m1-cannot-mine-unpinned-test-dependencies.md) | M1's host-execution model cannot mine a repository whose test dependencies are unpinned | Accepted · extends 0013 |
| [0020](0020-the-wrap-phase-offers-the-retro-first.md) | The `/ship` wrap phase offers the retro before ADRs, map, docs and git | Accepted |
