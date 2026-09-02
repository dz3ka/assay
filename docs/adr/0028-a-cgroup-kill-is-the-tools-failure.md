# ADR-0028: A trial killed at its cgroup ceiling scores `FAILED`, and the rule is read between the timeout and the band

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Bogdan Dzekic

## Context
`assay.score.score_report` is the only function that ever ranks a tool (SPEC §4 tier 1,
[ADR-0003](0003-rank-only-on-executable-signal.md)). It reads one `TestReport` and answers
`PASSED`, `FAILED` or `ERRORED`, and the whole point of the third answer is that a harness
malfunction must not print as a tool's confident zero. The rule it uses is the exit-code band:
pytest documents 0 through 5 and nothing else, so a report carrying anything outside that set was
produced by something other than pytest answering a question about the tests. `docker run` is the
case that motivated it — 125 when the client or the daemon failed rather than the command, 126 or
127 when the command could not be invoked. A pruned image tag would otherwise give every trial for
that task `pass@1 = 0.0`, *including* the ground-truth adapter whose 1.0 is the top of the bracket
every real result is read against.

That rule is right about 125, 126 and 127 and wrong about one number.

SPEC §9 requires a proof that a trial is **killed at its resource limit**, and
`tests/sandbox/test_container_policy.py` provides it: a probe that allocates 400 MiB inside a
container held to `memory_mb=64` is killed by the kernel's OOM killer, and the container exits
**137** — 128 + 9, SIGKILL, the status docker reports for a signalled container. Under the band
rule as written, that trial scored `ERRORED`.

That is a measurement error in the direction this project cannot afford. A tool that exhausted the
memory or the CPU ceiling it was handed **failed the trial**. Nothing about Assay malfunctioned:
the limits were applied as configured, the container ran, and the kernel answered. Scoring it
`ERRORED` lifts a real failure out of the denominator, and the tool that caused it is flattered by
exactly the trials it lost — the shape CLAUDE.md calls a confident number nobody should trust.

The complication is that Assay's own timeout kill produces 137 at the same seam. `run_in_sandbox`
kills a container that outruns its wall-clock budget, and docker reports that kill as 137 too. Two
different facts, one number, one layer down.

## Decision
**Exit code 137 scores `Outcome.FAILED`, not `Outcome.ERRORED`**, and the check sits **after the
`timed_out` branch and before the band check** — `_RESOURCE_KILL_EXIT_CODE` in
`src/assay/score/executable.py`.

The position is the load-bearing half of this record, and it is what makes the two 137s separable
without a heuristic:

- **After `timed_out`.** A run Assay killed never reaches the scorer wearing 137.
  `SandboxTestRunner.run` catches `CommandTimeoutError` and returns a report with
  `exit_code = _KILLED_EXIT_CODE` (`-1`) and `timed_out=True`; `assay.host.pytest_runner` does the
  identical conversion for the host runner. The sentinel is negative precisely so it can never be
  confused with a code anything else produces. **Therefore a 137 that arrives here is necessarily a
  kill Assay did not send** — which leaves the cgroup ceiling as the sender. Placed before the
  `timed_out` branch, the rule would steal timed-out runs from a branch that already owns them and
  make the sentinel conversion look optional; both branches answer `FAILED` today, so the theft
  would be silent, and the next verdict added to either branch would make it loud in production
  rather than in a test.
- **Before the band.** The band answers `ERRORED` for every code outside 0–5, 137 included. Placed
  after it, the rule would be dead code that reads as live policy.

This **narrows** the band rule rather than contradicting it. The rule's justification was always
about *ambiguity*: an out-of-band code means something that was not pytest answered, and Assay
cannot tell from the number alone whether the trial was even attempted. 137 is not ambiguous. It is
a specific, measured, tool-attributable outcome — the only exit code in the harness with a
container policy behind it, a test that provokes it against a real daemon, and a `ContainerLimits`
value naming the ceiling that produced it. The band still governs everything it can actually speak
to.

The verdict is bound to the measurement rather than asserted twice:
`test_a_trial_is_killed_at_its_memory_limit` now feeds the exit code *the container produced* to
`score_report` and asserts `FAILED`. A unit test alone would only prove that the constant equals
itself.

## Alternatives considered
- **Leave 137 as `ERRORED`.** Rejected: it reports a tool's own resource exhaustion as Assay's
  malfunction. Under [ADR-0003](0003-rank-only-on-executable-signal.md) the executable signal is
  the ranking, and "the tool could not finish inside the resources it was given" is executable
  signal of the plainest kind. It would also make a memory-hungry agent *cheaper* to be, since its
  worst trials would leave the denominator.
- **Teach the sandbox seam to raise on 137 instead, so the scorer never sees it.** Rejected on two
  counts, and it is the alternative that looks tidiest. First, `run_in_sandbox` runs whatever argv
  it is handed — the network probes, the write probe and the version queries in `tests/sandbox` all
  go through it — so it has no standing to call 137 a fault; `test_container_policy.py` reads a raw
  137 through that function and calls it a *success*, which is the same function being asked to
  hold two opposite opinions. Second, a runner that raised would end a walk the `TestRunner`
  protocol requires it to let continue: a trial's failure is a value the caller records and moves
  past, not an exception that takes the run down. `executable.py`'s docstring already states this
  for the band as a whole and this record does not disturb it — the reading of an exit code belongs
  to the one function that knows the report came from a pytest run.
- **Read the signal rather than the number — ask docker for `State.OOMKilled`.** Rejected as a
  second, richer path into the same fact, for a distinction the verdict does not use. It would need
  a `docker inspect` per trial against a container `--rm` has already removed, and it would put a
  daemon round trip inside a pure, total scoring function. `TestReport` carries an exit code; the
  exit code is enough.
- **Give the resource kill its own `Outcome` member.** Rejected: `Outcome` is a versioned public
  schema ([ADR-0007](0007-suites-are-content-addressed-and-versioned.md)), and every reader — the
  Wilson intervals, `pass@1`, `pass^n` — would have to be told where the new member falls. It falls
  under "failed", which is where it already goes.
- **Order the check the other way and re-test `timed_out` inside it.** Rejected as the same logic
  written where it is harder to read. The sentinel conversion at the runner seam is the invariant;
  a scorer that re-derived it would be a second opinion about a fact one layer already settled.

## Consequences
A trial that OOMs is counted as a failure of the tool under test, so a memory-hungry agent's
`pass^n` now includes the trials it killed. That is the intended reading, and it means the resource
ceiling in `ContainerLimits` is a **measurement parameter**: a suite run under a tighter ceiling
will report lower scores for the same tools. The ceiling therefore belongs in the run's provenance,
alongside the suite digest, when `assay run` gains one in M3.

The separation depends on a fact stated in one place and enforced in another: the runners' `-1`
sentinel. If a future runner ever returned a killed run's raw exit code instead of converting it,
this scorer would call Assay's own timeout the tool's resource failure. Both runners' conversions
are covered by their own tests, and
`test_a_timed_out_run_that_also_exited_137_is_still_read_as_the_timeout` pins the scorer's side of
the contract — both branches answer `FAILED`, so that test documents the ordering rather than
proving it, and the proof that the rule is not dead code is the 137-without-timeout case.

137 remains a *success* to `run_in_sandbox` and a *failure* to `score_report`, deliberately. The
two functions are asking different questions about the same number, and this record is where that
is written down.
