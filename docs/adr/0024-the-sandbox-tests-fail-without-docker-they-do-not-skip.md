# ADR-0024: The sandbox tests fail when Docker is absent; there is no skip path and no availability guard

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Bogdan Dzekic

## Context
The sandbox is where every one of SPEC §5's non-negotiables is actually enforced. Model-generated
code only ever runs inside it; networking is off inside a trial
([ADR-0006](0006-network-off-inside-a-trial.md)); the repository under evaluation never leaves the
machine. Those are four sentences of prose until something proves them, and SPEC §9 names the
proofs: a trial cannot reach the network, cannot write outside the one directory it is given, and is
killed at its resource limit.

`tests/sandbox/test_container_policy.py` is where those sentences stop being claims. It runs a real
container against a real daemon, through `assay.sandbox.run_in_sandbox` — the same function
`SandboxTestRunner` calls — and asserts that a hostname does not resolve, that a raw address does
not connect, that `/etc` and `/opt/venv` are read-only, and that a probe allocating past its
`ContainerLimits` ceiling is killed. `tests/sandbox/test_runner.py` does the same for what a trial
*reports* out of that container. Neither can be written any other way: an argv assertion against a
mocked `run_command` proves that a particular command line is what Assay builds, which is a claim
about the test's own expectations, not about the kernel.

Every one of those assertions is a **negative**, and a negative is worth exactly what its test is
worth. The awkward property of a negative is that not running it looks almost the same as passing
it. A run that ends "passed", with a skip count beside it and no failures, reads as green. Nothing
in that line says the network-off guarantee went unchecked on this host, and nobody reads a skip
count looking for a guarantee — that is precisely the discipline an automated test replaces.

The conventional answer is `pytest.mark.skipif` on daemon availability, and for most repositories
with container tests it is the right answer, because there the container tests are a convenience.
Here they are the thing being sold. CLAUDE.md states the standard the project is measured against:
a harness that produces a confident number nobody should trust is worse than no harness. A suite
that quietly does not prove its sandbox negatives, on a host that cannot prove them, and reports
green anyway, is that failure in miniature — the harness making a confident claim about itself.

The direction of the failure decides it. CI has a daemon; a developer's machine may not, especially
the machine of the person editing container policy, which is when these proofs matter most. A skip
guard fails open exactly there.

## Decision
**`tests/sandbox` talks to a real Docker daemon unconditionally. There is no marker, no
`skipif`, no `--run-sandbox` opt-in, and no daemon-availability probe anywhere in the suite. If the
daemon is not up, the suite is red, and that is the intended report.**

The mechanism is the absence of a mechanism, so the policy is written down where a reader meets it
rather than encoded in a fixture. `tests/sandbox/support.py` states it beside the scaffolding every
sandbox module imports, and `test_container_policy.py` and `test_runner.py` repeat it in their own
headers, because someone arriving at the network-off proof needs to know it is unconditional
*there*, not two files away.

The configuration reinforces it without being asked to. `pyproject.toml` runs pytest under
`--strict-markers` and registers no markers at all, so a `@pytest.mark.sandbox` cannot be added
without also declaring it in the config — the opt-out cannot be slipped in as a one-line decoration
on a test.

CLAUDE.md's milestone discipline is the other half: a milestone is never complete with skipped
tests. M2's verify baseline is therefore stated as **passed with zero skipped**, and the zero is
load-bearing. It is what makes "the sandbox negatives were proved on this run" readable from the
last line of the run, rather than from a marker's condition and a mental model of the host.

**The cost is accepted rather than mitigated.** On a host with no daemon, every test in
`tests/sandbox` that builds an image or starts a container fails — roughly twenty of them, spread
across all three modules. That is an environment failure to fix, not a code defect, and it must not
be repaired by adding a guard.

## Alternatives considered
- **`pytest.mark.skipif` on daemon availability.** Rejected, and it is the obvious one. It converts
  an unproved guarantee into a green run, on exactly the hosts where the guarantee is least likely
  to hold, and it makes the skip count the only place the loss is visible. It also fails open under
  change rather than under absence: a daemon that is up but broken — an exhausted disk, a wedged
  containerd — would be probed as "available" by any cheap check and the tests would fail anyway,
  so the guard buys nothing for the case it is nominally for while costing everything for the case
  it is not.
- **A `sandbox` marker deselected by default, with a `--run-sandbox` flag to opt in.** Rejected as
  worse than the skip. It makes proving the negatives conditional on somebody remembering a command
  line argument, so the default run of the default command reports green having checked nothing, and
  CI's greenness becomes a property of its invocation rather than of the suite. It would also need
  the marker registered under `--strict-markers`, which is the opt-out written into the project's
  own configuration.
- **Mock the daemon: patch `run_command` and assert the docker argv.** Rejected, and it is the
  seductive one, because it would make these tests fast, hermetic and runnable anywhere. What it
  would assert is that Assay passes `--network none`, not that `--network none` stops a socket from
  opening. The value in `test_container_policy.py` is entirely in the second claim: a real container
  really failed to resolve `example.com`, and really was killed by the kernel's OOM killer at the
  ceiling `ContainerLimits` set. A mocked version of that file would be a test of the test's
  assumptions, held up as proof of a security boundary.
- **A session-scoped fixture that probes the daemon once and fails fast with a clear message.**
  Rejected, though it is the closest call here, because it looks like a courtesy rather than an
  escape. It is still a daemon-availability probe — the exact mechanism this record refuses — and it
  is one edit from becoming a skip the first time the red is inconvenient. It would also collapse
  the report: instead of naming which proofs did not happen, the run would show one setup error and
  a large number of tests that never reported at all.
- **Split the suite so CI runs the sandbox tests and developers do not.** Rejected: it is the same
  skip with more infrastructure, and it separates the edit from its proof. A change to the container
  policy would go green in the run the author actually watches, and be contradicted somewhere else
  later, which is how a policy regression gets committed with a passing local suite behind it.

## Consequences
Running Assay's suite requires a Docker daemon. That is now part of what the suite *is*, not an
optional extra, and a contributor without one cannot get a green run — the failures they see are
accurate, and the fix is to start the daemon.

The sandbox tests are also the slow ones: a cold run pulls a base image and installs the project and
pytest before anything is asserted. `support.fixture_image` amortises that across a module because
the tag is a content address over pinned fixture commits, so the daemon already holds the layers
after the first run. Speed pressure is the force most likely to produce a proposal to skip these
tests, so it is named here as a cost to be paid rather than a problem to be solved.

The two module headers that cite this record — `test_container_policy.py` and `test_runner.py` —
now resolve, and `tests/docs/test_adr_index.py` keeps the citation and the file honest in both
directions the way it does for every other ADR.

Nothing here constrains how a *trial* behaves; it constrains how Assay's own suite reports on
itself. The trial-side guarantees are ADR-0006's and SPEC §5's, and this record is only the decision
that they are never allowed to go unmeasured while the report still says green.
