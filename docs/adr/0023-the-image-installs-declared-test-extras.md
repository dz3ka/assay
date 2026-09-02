# ADR-0023: The task image installs the repository's declared test extras, and ADR-0018 stops at the host

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0018](0018-provisioning-installs-the-runtime-set-and-pytest.md) fixed the install at `-e .`
plus pytest, no optional extra and no dependency group, and it has a measured cost. httpie keeps
its test dependencies in a `test` extra, so its `tests/conftest.py` cannot import `pytest_httpbin`,
pytest exits 4 having collected nothing, and the gate is handed evidence about the environment
rather than about the commit.

M2's pinned re-mine did not move that. Three candidates reached the gate, all three images built in
seven to eight seconds, and all three produced the same `ModuleNotFoundError`
([`docs/milestones/m2-yield-httpie-pinned.md`](../milestones/m2-yield-httpie-pinned.md)). The
milestone document says why in one line: layer 1 was never about pinning, it is about which
dependency sets get installed, and that decision lived in ADR-0018 rather than in the image.

This is not a second patch chosen after seeing a number.
[ADR-0021](0021-resolution-is-pinned-to-the-base-commit-era.md) fixed M2's stop rule in advance —
one widening, chosen before the measurement — and named both of its halves there: *"epoch-pinned
resolution, together with the declared test extras that narrow ADR-0018, is that one widening."*
This record is the second half, and it opens nothing that record did not already close.

ADR-0018 rejected extras on two grounds, and they have moved apart. The first — *the name is a
guess* — is answerable by reading instead of guessing, if there is somewhere to read from. The
second — *a right guess would have bought httpie nothing*, because a modern resolver broke the run
anyway — is ADR-0021's subject and is discharged there.

Where the extras are declared is the part that cannot be settled on the host. A repository declares
them in `pyproject.toml`, in `setup.cfg`, or only in `setup.py`, and the last is an answer that
exists only once the packaging code has run. This is not hypothetical for the repository M2 is
measured against: one of the three candidates is based on `3de7c82077ab`, the parent of httpie's
"Migrate setup.py to setup.cfg" commit, so its tree has no `setup.cfg` to read. Running a mined
repository's packaging code on the host is exactly what SPEC §5.2 forbids and what M2 moved into
the sandbox.

## Decision
**ADR-0018 is amended, its scope narrowed, and it is not superseded.** Its sentence —

> Where that environment cannot run the repository's tests, M1's posture is to report the limit
> rather than widen the install

— keeps binding [`host/venv.py`](../../src/assay/host/venv.py). `provision_venv` is untouched: it
still runs one install, still `-e . pytest`, still no extras. The rule stops at the host boundary,
and the image decides its own install set.

The build therefore has **two phases**. The first is today's recipe, byte for byte. The built image
is then asked what the project declares — `read_declared_extras` reads `Provides-Extra` off the
distribution whose PEP 610 `direct_url.json` points at `/workspace`, in a container with
`--network none`. `_select_extras` keeps the names in `TEST_EXTRA_NAMES` — `test`, `tests`,
`testing`, `dev` — case-folded, deduplicated, and rendered in the allowlist's own order rather than
the metadata's, because the clause reaches a content address and the arrival order belongs to a
packaging backend. If anything survives, a second phase installs `-e '/workspace[…]'` over the
first image, under the same cutoff, addressed by its own tag. **If nothing survives, the first
phase's tag is the answer, byte for byte** — which is every image this repository's own suite
builds.

Two properties make this a reading rather than the guess ADR-0018 refused. Assay only ever installs
an extra the repository *says it has*, so a wrong allowlist entry can fail to find a test set but
can never invent one. And the allowlist is closed: `docs` and `lint` are dropped silently, so
ADR-0018's real objection — that installing every declared extra maximises the resolver surface —
stands unamended.

## Alternatives considered
- **Parse `pyproject.toml` or `setup.cfg` on the host.** Rejected, and it is the obvious one. It is
  blind to a `setup.py`-only project, which is the state of one of the three candidates measured
  above, and covering that case means executing the repository's packaging code on the host — the
  exposure M2 exists to remove.
- **Take the extra as a CLI flag, `--install-extra test`.** Rejected again, having been ADR-0018's
  closest call. It was honest there because nothing could read the answer; now something can, and a
  flag whose correct value the caller also cannot check is a surface that looks like a fix.
- **Install every extra the repository declares.** Rejected on ADR-0018's ground, unchanged: it
  maximises the resolver surface to install dependency sets that have nothing to do with tests.
- **One phase, with the extras resolved before the build.** Rejected: the answer only exists once
  the project is installed, so a single phase would have to obtain it the way the first alternative
  does.
- **Keep ADR-0018 whole and report the limit.** Rejected here, having been *accepted* in ADR-0018 —
  because ADR-0021 already spent M2's one widening on precisely this, in writing, before the
  measurement. Declining it now would leave that allowance unspent and the zero unexplained.
- **Supersede ADR-0018 outright.** Rejected: its rule is still correct about the host, where there
  is still no image to read from and a guess would still be a guess.

## Consequences
`provision_venv` and M1's yield document stay true exactly as written; nothing in `assay.host`
changes, and M1's numbers keep the environment they were measured in.

Every image the suite already holds keeps its address, because the fixture repository declares no
optional dependencies at all. The cost is one extra container per build — an interpreter start,
seconds — paid by every build including the ones that widen nothing.

A repository whose test dependencies live under some fifth name is still out of reach, and is
reported as such rather than guessed at. Adding a fifth name is a decision that amends this record;
`TEST_EXTRA_NAMES` is not a config key and has no second consumer.

An image that cannot be asked what it declares raises `CommandFailedError`, the same error a failed
build raises, so a composing caller counts the commit `unprovisioned` and the walk continues. That
is deliberate: "no distribution was installed from `/workspace`" is a broken image, not a project
without extras, and the two must not arrive as the same answer.

ADR-0018 is not edited. This set records an amendment in the amending record and in the index row,
as ADR-0021 does for ADR-0019; an ADR is immutable once accepted, and a back-pointer written into
one is a second place for the two to disagree.
