# ADR-0021: Dependency resolution is pinned to the base commit's era, once, at image build time

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Bogdan Dzekic

## Context
M2 built what [ADR-0019](0019-m1-cannot-mine-unpinned-test-dependencies.md) named as the fix — a
pinned per-task container image — and re-mined httpie against it. The re-mine measured **zero valid
tasks** ([`docs/milestones/m2-yield-httpie-pinned.md`](../milestones/m2-yield-httpie-pinned.md)).

The image pinned the wrong half. `assay.sandbox.image` bakes the dependency set in *before* the
trial, which is what [ADR-0006](0006-network-off-inside-a-trial.md) needs and what stops a tool
installing its way to a passing test. But the set it bakes in is resolved **on the day the image is
built**, against today's index, for a tree that may be six years old. The commit is pinned; the
environment around it is not. A 2019 commit's tests then fail inside a 2026 transitive dependency,
the gate sees a repository whose tests do not run, and it says so — correctly, and about nothing
([ADR-0017](0017-still-red-stays-merged-until-m2-pins-the-environment.md)).

So ADR-0019's diagnosis was right and its remedy was under-specified: *installed at build time* is
not the same property as *resolved as of the commit*. Only the second makes a mined task's
environment a fact about the commit rather than about the day the harness ran.

## Decision
The task image resolves dependencies **as of the base commit's committer date**, by passing
`uv pip install --exclude-newer <date>` inside the build. The cutoff is rendered into the
Dockerfile, so it enters the image's content address the way every other line of the recipe does
and two eras cannot share a tag. `GitHistory.committed_at` supplies the date as `%cI`; it is the
*committer* date and never the author date, so a rebased commit's cutoff cannot predate the tree it
produced. `exclude_newer=None` still means today's index, and renders the recipe every image
already built was addressed by.

This is **build time only, and it changes nothing about a trial.** ADR-0006 is untouched: the trial
still runs with `--network none`, model-generated code still never runs on the host (SPEC §5.2),
and the network the build uses is the network `docker build` has always used. The build is not the
trial, and this record turns on that distinction.

It **amends ADR-0019**, which said:

> When a repository is out of reach, the honest M1 posture is to **report the limit and the zero**,
> never to widen the install until something passes.

That sentence stands for M1 and is superseded for M2 only under a rule fixed in advance, because
without one it is indistinguishable from tuning a harness until its number improves:

> **One widening, chosen before the measurement, and one only. If the re-mine still yields zero,
> that is a finding — about the repository and about Assay's reach — and not a licence for a second
> patch.** Epoch-pinned resolution, together with the declared test extras that narrow
> [ADR-0018](0018-provisioning-installs-the-runtime-set-and-pytest.md), is that one widening. A
> third would be a guess whose success is invisible from inside Assay.

ADR-0019 rejected epoch-pinning for M1 on three grounds. Two are discharged by where the code now
sits; the third is not, and is stated rather than solved:

- *"it needs the network per commit on the host"* — **discharged.** Resolution happens inside
  `docker build`, not on the host and not inside a trial. Neither the host's exposure
  ([ADR-0013](0013-mining-runs-on-the-host-in-m1.md)) nor the trial's isolation changes.
- *"it puts a resolution policy into the miner that M2's image is going to own anyway"* —
  **discharged, because this is that ownership.** The policy lives in `assay.sandbox.image`, in the
  recipe, addressed by the tag. `assay.mine` never learns that a commit has a date at all:
  `committed_at` is deliberately not on the `History` protocol.
- *"it does not reconstruct yanked or deleted releases"* — **still true.** See Consequences.

## Alternatives considered
- **One fixed global cutoff for the whole run — a `--resolve-as-of` flag.** Rejected, and it is the
  closest alternative: simpler, one number a human can state, and it would have fixed a
  single-commit reproduction. It cannot fix a *walk*. Assay mines a repository's whole history, so
  the normal case is two candidates from different eras in one run, and any single cutoff is wrong
  for at least one of them — too new for the old commit, too old for the new one, and silently so.
- **Resolve once, lock the result, reuse the lock across the walk.** Rejected for the same reason
  with a cost added: the lock would be a dependency set nobody chose, shared by commits years
  apart, and every task mined under it would be measured in an environment that never existed.
- **Vendor a wheelhouse per era.** Rejected as out of proportion: it is a package mirror, bounded
  by disk rather than by the repository, and `--exclude-newer` buys most of it for one flag.
- **Accept the zero and report it.** Rejected here, having been *accepted* in ADR-0019 — the
  difference is that M1 had nowhere to put the fix and M2 does. Publishing a zero produced by a
  known, nameable, fixable defect in Assay's own environment construction would be this project's
  subject matter failing inside the project.
- **Widen further until something passes.** Rejected in advance by the stop rule above, which is
  why it is written down before the next measurement rather than after it.

## Consequences
Two limits are real, and are stated rather than mitigated.

**Yanked and deleted releases still drift.** `--exclude-newer` filters the index by upload date; it
cannot restore a file PyPI no longer serves. The drift is *monotone*, and that is what makes it
tolerable: everything published after the cutoff is excluded, so the reachable set can only lose
members over time and never gain them. A rebuild months later can therefore **fail**, but it cannot
quietly resolve to something else and pass. A harness that reproduces or refuses is one this
project can defend; one that reproduces differently is not.

**The interpreter is not epoch-pinned.** Every task image is the same digest-pinned CPython 3.12,
so a commit from an era whose build backend cannot run on 3.12 fails at build rather than
resolving. That failure is loud — `CommandFailedError` carrying BuildKit's stderr — and it is a
genuine narrowing of reach rather than a silent wrong answer. Per-era base images are an M3+
question and are not opened here.

Every commit built with a cutoff gets a new tag, which is correct and is what the content address
is for: an image resolved as of 2019 is not the image resolved today, and a trial scored against
one must not be attributable to the other. Images already built with `exclude_newer=None` keep
their tags exactly, because the recipe rendered for them is byte-identical to the old one.
