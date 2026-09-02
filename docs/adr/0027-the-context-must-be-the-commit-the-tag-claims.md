# ADR-0027: A task image's build context is proved to be the commit its address claims

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Bogdan Dzekic

## Context
`image_tag` ([ADR-0007](0007-suites-are-content-addressed-and-versioned.md),
[`src/assay/sandbox/image.py`](../../src/assay/sandbox/image.py)) hashes three things into a task
image's tag: the pinned base image, the recipe text, and `base_commit`. Two of the three are read
off values this module produced itself. The third is a *claim about a directory somebody else
handed us*, and until now nothing checked it. `build_task_image(context=..., base_commit=...)`
copied whatever tree it was pointed at and tagged the result with whatever sha it was told.

That gap has a specific, cheap failure. A trial workspace is a checkout that has had the task's
`test_patch` — and then the tool's own work — applied to it. Composing the image build with the
trial loop by handing the *workspace* to `build_task_image` produces an image whose address names
the base commit and whose content is the patched tree. Nothing downstream can notice: the tag is
what every later step reads, so the recorded closure, the cache hit on a rebuild, and the result
row all agree with each other and are all about a tree nobody chose. That is a confident number
nobody should trust, which CLAUDE.md calls worse than no harness.

The M2 scratch harness behind [`m2-yield-httpie-pinned.md`](../milestones/m2-yield-httpie-pinned.md)
already got this right, and the way it did is the tell: it opened a clean worktree of the base
commit and built from that, with a comment saying so — "a clean checkout, not the patched
workspace". The comment *is* the precondition, and a comment is exactly what does not survive the
next composition. M3 has to wire this into `assay run` through a `RunnerFactory`, and the correct
wiring opens its own clean worktree — a thing to remember at the moment somebody is trying to make
a trial run at all.

The seam to check it through already exists: [`src/assay/host/git.py`](../../src/assay/host/git.py)
gained `checkout_state(path)`, which answers what commit a directory holds and how its tree differs
from it, in the one place Assay is allowed to run git.

## Decision
**`build_task_image` refuses a context it cannot prove is a clean checkout of `base_commit`**, and
does so before any image is built. `_checked_context` asks the host seam that one question, and
`_context_divergence` — pure, over a `CheckoutState` — decides what the answer means: a head that
is not `base_commit`, or any `git status --porcelain` entry whose path is not excluded from the
build context, is divergence. The refusal is a `SandboxError` naming the diverging entries; a
directory git cannot answer for at all is the same refusal, with the `GitError` chained.

`image_tag` is unchanged, and that is deliberate: **the address does not move.** Every image in a
daemon's cache and every tag in a recorded result goes on meaning exactly what it meant. What
changes is only which contexts are allowed to reach it.

The exclusions are one list. `_CONTEXT_EXCLUSIONS` — `.git`, `.venv`, `__pycache__` — is what the
build's dockerignore is rendered from *and* what the divergence filter forgives, because the two
have to agree by construction: a `.venv` a host provisioning run left behind never reaches the
image, so refusing to build over it would be a false refusal, and a harness that will not mine the
trees it is pointed at measures nothing. Spelled twice, the lists drift silently in both
directions — an image quietly holding the host's scratch state, or a refusal of a context that was
fine.

Two consequences of the check are stated here rather than left to be discovered.

**A walk that dies on a composition bug is intended, not a gap.** A `SandboxError` from this
precondition means the harness handed a build the wrong directory. That is a property of Assay's
own wiring, not of the commit under test, so it must **not** be caught and counted as
`unprovisioned` the way an unbuildable environment is
([ADR-0026](0026-the-image-residue-is-reported-not-counted.md)). Swallowing it would turn one
mis-composed run into a plausible-looking yield table with a quietly smaller numerator — the
failure mode this project exists to detect, reported as a measurement. M3's `RunnerFactory` work
should open its own clean worktree per base commit and let this error kill the run; catching
`SandboxError` in the factory would be a regression of this record.

**`checkout_state` splits porcelain output on newlines, and that residual is accepted.** Every
other reader in `host/git.py` takes `-z` records precisely because git's output shape is not to be
trusted, and with `core.quotePath=false` forced a filename containing a literal newline is emitted
raw and would mis-split into two bogus entries — which reach this decision, because
`_context_divergence` reads a path out of each line. The failure direction is **closed**: a bogus
entry is a path matching no exclusion, so it reads as divergence and the build is *refused*. The
unsafe half — a divergent context accepted as clean — is not reachable this way, since no
mis-split can delete an entry or turn one into an exclusion. A refusal a maintainer has to go and
look at is the acceptable half of a parsing limit, in a harness whose subject is measurement
honesty. Recorded rather than fixed, in the posture ADR-0026 set: the residue is reported, not
gold-plated away.

## Alternatives considered
- **Leave it to the caller and keep the comment.** Rejected — that is the status quo that motivated
  the record. The scratch harness's comment was correct and load-bearing, and the next caller does
  not read it. A precondition that holds only when somebody remembers it is a convention, and
  `_checked_extras` already refuses that trade one seam away.
- **An `assume_clean=True` opt-out for callers that know better.** Rejected by design, and it is
  the tempting one because it would make a test or two cheaper. A flag whose only effect is to skip
  the check *is* the old comment wearing a keyword argument — and the comment is what failed. It
  also fails the "config needs a second consumer" rule: the only consumer would be a caller
  building from a tree it cannot describe, which is the case the check exists for.
- **Derive `base_commit` from the context instead of checking it against it.** Rejected. It reads
  as strictly simpler and quietly moves an address: a caller who checked out the wrong commit would
  get a perfectly consistent image for a commit the suite is not about, and the mismatch — the
  actual bug — would be gone from the record. Refusing keeps the caller's claim and Assay's
  observation both visible, which is the only way the disagreement can be reported at all.
- **Check the head only, not the working tree.** Rejected: the patched-workspace case is what
  motivates the record, and a patched workspace has exactly the right head.
- **Switch `checkout_state` to `-z` records first.** Rejected as gold-plating an already-closed
  failure direction, and it is not free: that contract is discharged and tested, `-z` splits a
  rename into two records, and `_context_divergence` would then need a special case for a shape
  that cannot occur — git tracks nothing under `_CONTEXT_EXCLUSIONS`, so a rename is never excluded
  anyway. If a repository ever lands on the newline case, the evidence is a refusal quoting a bogus
  entry, which is a bug report rather than a wrong number.
- **Repair the tree instead of refusing it — `git stash`, `git checkout --`, a fresh clone.**
  Rejected outright. Assay does not own the tree it is measuring (SPEC §5.1), and a harness that
  reset somebody's checkout to make its own address true would be corrupting the measurement rather
  than taking it. Refuse, never repair, is the posture `_checked_cutoff` already takes at this
  boundary.

## Consequences
Every build context is now a git checkout, in the tests as well as in production: the extras
fixture in `tests/sandbox/test_image.py` became a one-commit repository with its identity, both
timestamps, line endings and file mode pinned, because that commit's object name enters a content
address and a sha that moved with the host's clock would charge every run for a cold rebuild of an
image the daemon already holds. That is this record's standing cost — a build context can no longer
be a bare directory anywhere.

Each build pays two git plumbing calls, `rev-parse` and `status`, against its own deadline. On a
tree the size of httpie that is milliseconds against a build measured in seconds, and it is charged
through the existing `_remaining` helper so the precondition cannot eat a budget it does not own.

`assay.sandbox` now asks git exactly one question, through `assay.host`. The layering is unchanged —
this package still runs no git of its own and holds no `GitHistory` — but the docstring claim that
it "never asks git anything" was falsified by this change and has been amended where it stood.
`exclude_newer` is still passed rather than derived, for the reason ADR-0021 gives: the cutoff is a
fact about the commit's *history*, which only a `GitHistory` bound to the clone can answer, while
the precondition is a fact about a *directory*.

The check is only as good as its exclusion list. A dockerignore pattern without `**/` matches at
the top level only, so `widget/__pycache__` *does* reach the image and *is* divergence, while a
top-level `__pycache__` is not; that asymmetry looks like an oversight and is not one, and it has a
test pinning both directions.
