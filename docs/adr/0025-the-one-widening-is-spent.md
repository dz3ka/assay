# ADR-0025: The one widening is spent, and what it still cannot reach is reported rather than patched

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0021](0021-resolution-is-pinned-to-the-base-commit-era.md) allowed itself exactly one widening
of the task image, chose it before the measurement, and wrote the stop rule down so that the next
result could not be argued with:

> **One widening, chosen before the measurement, and one only. If the re-mine still yields zero,
> that is a finding — about the repository and about Assay's reach — and not a licence for a second
> patch.**

That widening — epoch-pinned resolution plus the declared test extras of
[ADR-0023](0023-the-image-installs-declared-test-extras.md) — has now landed and been measured
against the same 40 commits of httpie the pre-fix run walked
([`docs/milestones/m2-yield-httpie-pinned.md`](../milestones/m2-yield-httpie-pinned.md)). The
measurement is mixed in a way that makes both halves easy to overstate, so both are recorded here:

**The environment blocker lifted.** Inside a post-fix image, httpie's suite collects **1028 tests
and 998 pass**, with no network, resolved as of the commit. `pytest-httpbin==2.0.0` is installed —
ADR-0019's layer 1 — and `jsonschema-specifications==2023.12.1` rather than a 2026 release is
installed — its layer 2. Under M1 the same repository could not collect a single test.

**The yield did not move: 40 commits examined → 0 valid tasks.** Two candidates reached the gate
and both changed test *machinery* rather than a test module — a helper package, a conftest, a
vendored fixture — so pytest was pointed at files holding no tests and correctly reported that
nothing ran. They are not test-anchored fixes and discarding them is right. A third candidate was
lost before the gate: its May 2023 closure wants `multidict==6.0.4`, whose wheels predate CPython
3.12, so uv fell back to a source build in an image with no compiler. It is counted `unprovisioned`.

**The full 743-commit walk then measured the same thing at scale, and it is the harder number.**
743 commits examined → 0 valid tasks, with **125 counted `unprovisioned`**: of the 126 base
images the walk attempted, **124 failed to build**, every one of them from before March 2024.
The failures group into three messages — `No module named 'distutils'` (90), `pkgutil` has no
attribute `ImpImporter` (31), and a source build of `multidict==6.0.4` with no compiler (3) —
and all three are one cause: **the dependency set is now the commit's era and the interpreter is
still 2026's.** The resolution is right and the build backend it hands the sdist to is written
for a Python that no longer behaves that way.

So the zero did not move and the *meaning* of the zero moved completely — from "Assay cannot
build an environment for httpie" to "Assay can build 2024 and cannot build 2019–2023, and it
says so in a count that sits outside the gate's verdicts." That is the finding the stop rule was
written to protect, and it arrives with three obvious next patches visibly available: install
`gcc`, constrain `setuptools`, and pin the interpreter per era.

## Decision
**The widening budget is spent. It is now zero, and ADR-0019's posture is restored in full.** The
sentence ADR-0021 suspended for one measurement is back in force from here:

> When a repository is out of reach, the honest M1 posture is to **report the limit and the zero**,
> never to widen the install until something passes.

Read for M2 and after, with "M1" now meaning "whichever milestone is measuring": what the image
cannot reach is written into the milestone document as reach, and the number is published as it
came out. The five residues — yanked releases, the un-pinned interpreter, undeclared system
dependencies and services, extras outside the four-name allowlist, and pytest-era junit calibration
— are named in prose in that document precisely so that nobody has to rediscover them by watching a
number fail to improve.

This **amends [ADR-0019](0019-m1-cannot-mine-unpinned-test-dependencies.md)** a second time, and
settles the three grounds on which it rejected epoch-pinning for M1 — the first two by measurement
rather than by argument this time:

- *"it needs the network per commit on the host"* — **discharged.** Resolution happened inside
  `docker build` for all 40 commits. No target code ran on the host and no trial saw a network.
- *"it puts a resolution policy into the miner that M2's image is going to own anyway"* —
  **discharged, and the ownership is now exercised.** The policy is a rendered line in
  `assay.sandbox.image`, hashed into the tag; `assay.mine` still does not know a commit has a date.
- *"it does not reconstruct yanked or deleted releases"* — **still true, and now auditable.**
  `read_installed_closure` records what an image actually holds, so a rebuild that fails is
  distinguishable from one that quietly resolved to something else. The pin is monotone, so only
  the first of those can happen; the closure is how that claim is checked rather than asserted.

## Alternatives considered
- **Install `gcc`, or add a `setuptools` constraint, or both.** Rejected, and this is the closest
  call by a distance: each is one line, a compiler in a build stage is unremarkable engineering,
  and between them they address 124 failed images. They are refused because they were chosen
  *after* seeing which commits failed and what they printed, which is the definition of the
  tuning this project exists to detect. A `setuptools` pin is also not a small change dressed as
  one: it would put a resolution decision Assay invented into an environment that is supposed to
  be the commit's, so a task mined under it would be measured in a world that never existed —
  ADR-0021's own argument against a global cutoff, pointed at a single package.
- **Add a fifth allowlisted extra name.** Rejected for the same reason and with less to show for
  it: the two names httpie declares both fired, so no measured commit is waiting on a fifth.
- **A single fixed global cutoff — one `--resolve-as-of` for the whole run.** Rejected in ADR-0021
  and re-recorded here because it is the alternative that keeps getting re-proposed on the grounds
  of simplicity. A walk's normal case is two candidates from different eras of one repository —
  this pilot alone spans March 2024 and May 2023 — and any single cutoff is wrong for at least one
  of them, silently.
- **Read the extras off `pyproject.toml` or `setup.cfg` on the host instead of asking the image.**
  Rejected twice over. It is blind to a `setup.py`-declared extra, and candidate `3de7c82077ab` is
  literally the commit that *introduces* httpie's `setup.cfg` — its parent declares everything in
  `setup.py`. And reading a `setup.py` means executing the repository's packaging code on the host,
  which is the exposure M2 moved into the sandbox ([ADR-0013](0013-mining-runs-on-the-host-in-m1.md)).
- **Declare the reach limit lifted and publish a yield for httpie.** Rejected. The suite running
  inside the image is evidence about Assay's reach; it is not a yield. The full walk examined 743
  of 1690 non-merge commits and never evaluated 125 of the 127 that got past the pre-gate split,
  so no denominator here prices the repository.
- **Keep widening quietly and report only the final number.** Rejected outright. It is the failure
  mode this repository was built to make visible, and it would be undetectable from the outside —
  which is exactly why the stop rule was written before the measurement rather than after it.

## Consequences
A third widening now needs its own ADR arguing from something other than a disappointing number,
and this record is what a reviewer holds it against.

The full 743-commit walk over M1's range was run under this rule and is reported with its
denominator: **743 commits examined, 0 valid tasks, 125 unprovisioned.** 124 of the 126 base
images it attempted failed to build, every one of them older than March 2024, and every failure
traces to the un-pinned interpreter — an era build backend meeting CPython 3.12. That is the
residue this record refuses to patch, measured at scale rather than predicted, and it makes
**per-era base images** the decision M3 has to take. Taking it now, with the failing commits in
view, would be the second widening.

`read_installed_closure` becomes part of what a run records rather than a debugging convenience:
without the closure beside a result, "this environment is reproducible" is a claim with nothing
behind it. It is not yet wired into any recorded artefact — `assay mine` has no pinned-image path
at all — and that wiring is M3's, along with the `Result` field the closure will eventually live in.
