# ADR-0019: M1's host-execution model cannot mine a repository whose test dependencies are unpinned

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0013](0013-mining-runs-on-the-host-in-m1.md) accepted host execution for M1 — a throwaway
worktree, an ephemeral `.venv`, the invoking user's account — and weighed it as a *security*
exposure. It named no limit on which repositories could be mined. The by-hand httpie run
([`docs/milestones/m1-yield-httpie.md`](../milestones/m1-yield-httpie.md)) found one, and found it
by measurement rather than by prediction.

743 commits examined → 0 valid tasks. 171 candidates reached the gate and not one was accepted, for
a single uniform reason in two layers. Layer 1: the provisioned venv has no test dependencies, so
httpie's `conftest.py` cannot import and pytest exits 4 having run nothing
([ADR-0018](0018-provisioning-installs-the-runtime-set-and-pytest.md)). Layer 2, which is the one
that matters: installing `-e .[test]` clears layer 1 and the tests **still** do not run, because uv
resolves the commit's unpinned transitive dependencies to *today's* releases and collection dies
inside a modern `jsonschema_specifications`.

Both layers are one root cause: **provisioning a historical commit against the present-day package
index, on the host, under the host's interpreter.** A commit's dependency closure as it stood on
the day it was written is not recoverable that way. The tree the miner checks out is exactly the
commit's; the environment around it is dated today, and the gate cannot tell the two apart — it
sees a repository whose tests do not run, and says so, correctly
([ADR-0017](0017-still-red-stays-merged-until-m2-pins-the-environment.md)).

## Decision
This is recorded as a **stated reach limit of M1, not a defect to be patched inside M1**:

> M1 can mine a repository whose test dependencies are pinned and installable from its own runtime
> packaging. It cannot mine one whose test dependencies are unpinned, or live in an extra or group
> that pinning does not cover.

ADR-0013 stands and is **extended, not superseded** — host execution remains M1's model, and this
record adds what that model cannot reach to what it costs.

The fix is M2's **pinned per-task image**: the dependency set resolved once at image build and
baked in, so a trial runs against the closure the task was mined with. That is not a new
requirement invented here — [ADR-0006](0006-network-off-inside-a-trial.md) already forbids the
network inside a trial, which forces the same pinned image for scoring. Mining and scoring
therefore need the same thing, and M2 builds it once.

When a repository is out of reach, the honest M1 posture is to **report the limit and the zero**,
never to widen the install until something passes.

## Alternatives considered
- **Widen the install until the suite runs — extras, then a resolver pin, then a constraints
  file.** Rejected on the measurement, not on taste: `[test]` was tried and moved exit 4 to exit 1
  with still no test executed. Each further widening is another guess whose success is invisible
  from inside Assay, and a guess that happens to make a suite run would mint tasks measured in an
  environment nobody chose.
- **Pin transitives by date — resolve against the index as of the commit's timestamp.** Rejected
  for M1: `uv --exclude-newer` makes this thinkable, but it needs the network per commit on the
  host, it does not reconstruct yanked or deleted releases, and it puts a resolution policy into
  the miner that M2's image is going to own anyway.
- **Restrict `assay mine` to repositories it can detect as pinned, and refuse the rest.** Rejected:
  the detection is a guess about packaging, a refusal would stop runs that would have worked, and
  the useful signal — 743 examined, 171 candidates, all discarded for one proven cause — is
  produced by *running* and reporting, which is how this limit was found in the first place.
- **Report httpie's 0 as httpie's yield.** Rejected outright, and it is the reason this ADR exists.

## Consequences
httpie yields 0 valid tasks under M1 **not because its history lacks test-anchored fixes but
because M1 cannot build the environment to see them.** The milestone document reports that yield as
an environment result and forbids quoting it otherwise: **the number is not a claim about httpie.**

M1's exit criterion is met by a fixture repository and a real-repository *run*, not by a real
repository's tasks, and this record is where that distinction is kept. M2 inherits a concrete
acceptance test: re-run this walk against pinned per-task images, and a `still_red` verdict then
means what it says.
