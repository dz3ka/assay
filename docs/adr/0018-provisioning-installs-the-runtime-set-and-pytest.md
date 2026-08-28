# ADR-0018: Provisioning installs the project's runtime set plus pytest, and no extras or groups

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Bogdan Dzekic

## Context
[`provision_venv`](../../src/assay/host/venv.py) (`venv.py:66`) runs `uv venv` and then exactly one
install: `uv pip install --python <venv> -e . pytest`. The project itself, editable, plus
`_TEST_RUNNER_REQUIREMENT` (`venv.py:47`), which exists because a repository declares pytest as a
development dependency or not at all, and a run that cannot start is evidence of nothing. **No
optional extra and no dependency group is installed.** That is a design choice, and until now it
was implicit — a call site, not a decision anyone could find or argue with.

It has a measured cost. httpie declares its test dependencies in a `test` extra, so the venv Assay
built could not import httpie's own test suite: `tests/conftest.py` raised
`ModuleNotFoundError: No module named 'pytest_httpbin'`, pytest exited 4 having collected nothing,
and every one of the 171 candidates was discarded on evidence about the *venv* rather than about
the commit ([`docs/milestones/m1-yield-httpie.md`](../milestones/m1-yield-httpie.md), layer 1;
[ADR-0017](0017-still-red-stays-merged-until-m2-pins-the-environment.md) for what that did to the
tally).

The obvious repair was **measured rather than assumed**, which is what makes this record worth
writing. Re-provisioning a candidate by hand with `-e .[test]` cleared the conftest import and
moved pytest from exit 4 to exit 1 — **and the tests still never ran.** uv resolves httpie's
unpinned transitive dependencies to *today's* releases against a years-old commit, and collection
died inside a modern `jsonschema_specifications` (`FileNotFoundError` on a
`schemas/draft202012/vocabularies/` resource). Installing the extra exchanged one environment
artifact for another. So "install more" is not the fix; the fix is
[ADR-0019](0019-m1-cannot-mine-unpinned-test-dependencies.md)'s subject.

## Decision
M1 provisioning installs **the project's own runtime dependency set and pytest, and nothing else**,
and that is now written down rather than inferred from a call site. The install is the smallest one
that can start a test run, deliberately: an environment Assay assembled by guesswork is an
environment whose failures are Assay's, and a mined result gains nothing by being measured in one.

Where that environment cannot run the repository's tests, M1's posture is to **report the limit
rather than widen the install** — the yield says so in words, and no dependency set is bolted on
in the hope of clearing a run.

## Alternatives considered
- **Install a named extra by convention — `test`, then `dev`, then `tests`.** Rejected: the name is
  a guess, the guess rate is unknown and unknowable from inside one repository, and a wrong guess
  fails as a resolver error partway through a walk rather than as a refusal at the start. Worse, a
  *right* guess would have bought httpie nothing — measured above — while making the next zero
  yield harder to diagnose, because the install would no longer be a fixed, stated thing.
- **Take the extra as a CLI flag, `--install-extra test`.** Rejected for M1, and this is the
  closest call: it is honest, since the caller states the guess rather than Assay making it. But it
  adds a flag whose correct value cannot be checked, on a surface that is about to be replaced by
  M2's per-task image, and the httpie measurement shows the flag would not have produced a task. A
  flag that looks like a fix and is not is the kind of surface this project should not ship.
- **Install nothing beyond `-e .` and let the runner report whatever happens.** Rejected: it is the
  status quo minus pytest, and without pytest most repositories produce a run that cannot start —
  the condition `_TEST_RUNNER_REQUIREMENT` was added for.
- **Read the repository's packaging and install every extra it declares.** Rejected: it maximises
  the resolver surface, so it maximises the chance of exactly the layer-2 failure above, and it
  installs dependency sets (docs, lint) that have nothing to do with running tests.
- **M2's answer: a per-task image whose dependency set is resolved and baked once at build.**
  Not rejected — **deferred**, and it is the real answer. It is out of reach here because M1 has no
  image to bake into (ADR-0013), which is precisely the reach limit ADR-0019 records.

## Consequences
A repository whose test dependencies are installable from its own runtime packaging mines correctly
today; one that keeps them in an extra or a group does not, and gets a zero yield whose cause is
Assay's environment. That is a stated limitation with a measurement behind it rather than a
surprise, and the milestone document is required to report it as an environment result.

The install line is one place, spelled once, and this record is what it points at when someone asks
why it is so small.
