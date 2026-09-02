# ADR-0030: An exit code pytest could not have produced means Assay malfunctioned, and scores `ERRORED`

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Bogdan Dzekic

## Context
`assay.score.score_report` ([`src/assay/score/executable.py`](../../src/assay/score/executable.py))
is the only function that decides a trial's executable verdict, and under
[ADR-0003](0003-rank-only-on-executable-signal.md) that verdict is the only thing a ranking is ever
built from. It reads one `TestReport` and answers `PASSED`, `FAILED` or `ERRORED`.

Two of those answers are claims about the tool under test. The third is a claim about Assay. The
whole difficulty of this function is that both arrive at it as the same kind of evidence — a
process ended, and left an exit code and some rows behind — and that the two must not print the
same number.

The tempting shape is two answers rather than three: a clean pass is `PASSED` and everything else
is `FAILED`. It reads as conservative, and it is the opposite. `docker run` is the case in hand. It
exits **125** when the client or the daemon failed rather than the command — an image tag absent
from this host, one `docker image prune` away — and **126** or **127** when the command could not
be invoked at all. Called `FAILED`, each of those records a run that never happened as a thing the
tool got wrong. It does so for the ground-truth adapter as readily as for a tool under test, which
silently removes the top of the bracket CLAUDE.md requires every real result to be read against:
the perfect-score adapter reports 0.0, and nothing anywhere in the output says a container failed
to start. That is precisely the confident number nobody should trust.

The arithmetic is not what is at stake, and saying so plainly is the only way this record is
readable. Under [ADR-0004](0004-pass-caret-n-is-the-headline-metric.md) an errored trial **stays in
the denominator and is not a pass**, so a task whose every trial exited 125 reports the same 0.0
either way. What the third answer buys is that the outcome carries the word `errored`, and a reader
— or the ground-truth adapter's own summary — can then tell "the tool did not fix it" from "no
container started". A wrong number that is legible as wrong is recoverable; one that is
indistinguishable from a finding is not.

What makes the distinction decidable at all is that pytest's exit codes are a **closed, documented
set**: 0 all passed, 1 tests failed, 2 interrupted, 3 internal error, 4 usage error, 5 no tests
collected. Finite and published, which is what makes the complement readable — a code outside the
set did not come from pytest, so whatever produced it was not answering a question about the tests.

`ERRORED` has a second half, and it belongs elsewhere.
[`src/assay/score/trial.py`](../../src/assay/score/trial.py) owns the case where an adapter reported
an error before any diff or any report could exist; it applies nothing, starts no container, and
records `ERRORED` directly. This record is about the half only a finished report can show.

## Decision
**An exit code outside 0–5 scores `Outcome.ERRORED`. Every code inside the band is the tool under
test's own result, and scores `PASSED` or `FAILED`.** The set is `_PYTEST_EXIT_CODES` in
`assay.score.executable`, spelled as the closed range rather than as a list of the failures Assay
happens to have met.

The band is read **on the report, in the scorer**, and not at the sandbox seam.
`assay.sandbox.run_in_sandbox` runs whatever argv it is handed — the network probes, the write
probe and the version queries in `tests/sandbox` all go through it — so it has no standing to call
any code a fault, and a runner that raised instead of reporting would end a walk the `TestRunner`
protocol requires it to let continue. `score_report` is the one place that knows the report came
from a pytest run *and* is free to say so in a verdict rather than in an exception.

**The order of the four branches is load-bearing at every position.**

- **A missing report, then `timed_out`, first.** A `None` report means the attempt diff did not
  apply or the workspace held no runner, and a timed-out run is the tool failing to finish inside
  the budget it was given; both are `FAILED`. `timed_out` must be read before the band because a
  run Assay killed carries the `-1` sentinel `SandboxTestRunner` and `PytestHostRunner` convert it
  to — a code out of the band by construction, which the band would otherwise call Assay's
  malfunction when it is the plainest executable signal there is.
- **The resource kill second, before the band.**
  [ADR-0028](0028-a-cgroup-kill-is-the-tools-failure.md) carves 137 back out and depends on this
  position: the band would otherwise answer `ERRORED` first and the carve-out would be dead code
  reading as live policy.
- **The band third, before the statuses.** Rows from a run pytest did not finish reporting on are
  not rows to rank a tool by. A junit file can be well-formed and full of passing rows while the
  process that wrote it died afterwards, so the statuses must never be reached for a code that says
  no pytest answered.
- **Zero versus nonzero fourth, inside the band.** The exit code carries what the statuses cannot —
  an error outside any test, a crashed plugin, a collection that never happened — so a run pytest
  itself called unhappy is not a pass, whatever the rows say.

This **narrows** [ADR-0003](0003-rank-only-on-executable-signal.md) rather than qualifying it.
ADR-0003 says a ranking may read executable signal and nothing else. This record says which numbers
*are* executable signal in the first place, and which are the instrument reporting on itself.

## Alternatives considered
- **Score every nonzero code `FAILED` and drop `ERRORED` from this function.** Rejected, and it is
  the one a reviewer should press hardest on, because it is simpler and because its failure mode is
  invisible. It costs nothing in the metric — the trials are already in the denominator either way
  — and it costs the report the only trace it has of the difference between "the tool did not fix
  it" and "nothing ran". The bracket that makes every other number readable would be gone, and it
  would be gone quietly.
- **Enumerate the codes a *runner* can emit instead of complementing pytest's.** Rejected: that set
  is open where pytest's is closed. 125, 126 and 127 are docker's today; a podman or a remote
  executor tomorrow would need the list edited, and the edit would be remembered only after a wrong
  number had been published. The complement needs no maintenance because the thing it is a
  complement of is fixed by pytest's own documentation, which is also the only set this function is
  entitled to reason about — it is scoring a pytest run.
- **Raise at the sandbox seam so the scorer never sees an out-of-band code.** Rejected for the two
  reasons ADR-0028 gives at more length: `run_in_sandbox` is not only ever handed pytest, and a
  raising runner ends a walk that a single bad trial should not end. A trial's failure is a value
  the caller records and moves past.
- **Widen the band to the shell's 124–127 family so a failure to invoke reads as a plain failure.**
  Rejected. Those codes name a failure to *start a command*, which is the definition of a trial that
  produced no evidence. Widening the band would buy tidier-looking output by turning the exact case
  the band exists for into a zero.
- **Give the harness's failure its own `Outcome` member, or attach a reason string to `ERRORED`.**
  Rejected: `Outcome` is a versioned public schema
  ([ADR-0007](0007-suites-are-content-addressed-and-versioned.md)), and a new member obliges every
  reader — the Wilson intervals, `pass@1`, `pass^n`, all three renderers — to be told where it
  falls. A reason is real information, but it belongs beside the trial in a run's provenance, and
  `assay run` is M3's to build; there is nowhere in M2's tree to put it that a report would read.

## Consequences
The shell's timeout family — 124 from GNU `timeout`, and 125, 126, 127 — stays outside the band and
keeps scoring `ERRORED`. **That is the intended reading and is not to be "fixed".** Each of those
codes says a command could not be started or could not be found, and a trial whose command never
ran is a trial with no evidence in it. The one number in that neighbourhood that *is* attributable
to the tool has its own record and its own branch above the band, which is ADR-0028 and 137.

`ERRORED` is therefore a real category with real occupancy, not a theoretical one, and the burden
this record creates lands on the report rather than on the metric. `assay.report.summarise` keeps
errored trials in the denominator on purpose, so their count is the only place a harness failure
shows; a reader who never looks at it sees an ordinary low score. Making that count impossible to
miss at the command surface is M3's, when `assay run` gains one.

The band's precision has a floor worth naming. A code *inside* 0–5 produced by something that was
not pytest is indistinguishable from pytest's own answer, and scores `FAILED` — a container whose
entrypoint fails early and exits 1 is the realistic shape. Nothing in the exit code can separate
those, so the protection this record buys is against the failures that announce themselves with an
unusual number, not against every possible one. That is the honest limit of reading a verdict off a
single integer, and the reason `assay.sandbox.container` documents which of docker's codes mean
what rather than leaving the scorer to infer it.
