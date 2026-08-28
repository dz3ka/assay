# ADR-0016: A below-floor `--test-timeout-s` is refused at the argument surface, not floored silently

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Bogdan Dzekic

## Context
`--test-timeout-s` is the ceiling on one pytest run, and a candidate that hits it is discarded as
`run_timed_out`. Underneath it, [`_remaining`](../../src/assay/host/pytest_runner.py)
(`pytest_runner.py:257`) returns `max(1, int(deadline - monotonic()))` — a one-second floor, called
twice per run, for the `--collect-only` pass (`:122`) and the measured `--junit-xml` pass (`:125`),
both charged against one `deadline = monotonic() + timeout_s`.

The floor is right for the job it was written for. Both passes share a budget, so after collection
the remainder can legitimately be zero or negative, and handing `run_command` zero kills a child
that was never given the chance to start — evidence of nothing. `venv.py` carries the same helper
for the same reason.

What the floor also does is absorb the *flag*. `--test-timeout-s 0` and `--test-timeout-s -1` both
reached the process layer as **1 second per pass, never 0** — the flag then meant something other
than what it said, and what it came to mean was not a shorter run but a machine-speed measurement.
(An earlier account of this reasoned from `subprocess.communicate(timeout=0)` raising
`TimeoutExpired` at once; that path is real in `subprocess` and unreachable from this CLI, because
the floor stands between them.)

Machine speed is the whole problem. pytest's startup measured about 0.28 s on the development
host, fast enough that SPEC §9's fixture repository mines clean at `--test-timeout-s 0` — nine
examined, two valid, exit 0. On a repository whose collection pass takes over a second, the same
command line discards *every* candidate as `run_timed_out` and still exits 0, having written a
zero-task suite that looks like a finding. One command line, two machines, two different
content-addressed suites: SPEC §5.5's reproducibility non-negotiable failing, not a usability wart.

## Decision
A below-floor budget is **refused at the argument surface**.
[`_test_timeout_seconds`](../../src/assay/cli/main.py) (`cli/main.py:184`) rejects `< 1` on **both**
`assay mine` and `assay validate`, as an `argparse.ArgumentTypeError` — stderr above the usage
line, `EXIT_USAGE`, before either command has executed anything belonging to the target repository.
The message names the floor rather than reciting a range, so a reader learns why the flag has a
minimum rather than only that it does.

The floor in `_remaining` **stays and is unchanged**: it is right for an exhausted shared deadline,
and was only ever wrong for a caller's stated ceiling, which is now checked where callers are. Its
own semantics remain **unpinned by any test** — a `tests/host/` test asserting that `_remaining`
returns 1 for an exhausted deadline, so the floor reads as deliberate rather than as an accident of
`max`, is a **named follow-up, not something the tree has**. The new CLI test guards the argument
surface only.

## Alternatives considered
- **Raise inside `_remaining` on a below-floor budget.** Rejected, not merely deferred: it cannot
  tell its two callers apart. A negative remainder after a slow collection pass is a *normal*
  outcome that should end as a `run_timed_out` verdict the yield counts, and raising there would
  turn it into a crash mid-walk.
- **Let the budget reach the subprocess as 0 and rely on `TimeoutExpired`.** Rejected: it swaps a
  silent reinterpretation for a silent zero yield. Every candidate would come back
  `run_timed_out`, the command would exit 0, and the semantics of the flag would live in a stdlib
  corner rather than in the flag.
- **Clamp to 1 and warn on stderr.** Rejected: the run still writes a suite, and a suite nobody
  should trust is not made trustworthy by a line above it.
- **Pin the floor with a test and change nothing at the surface.** Rejected as insufficient on its
  own: it documents the floor without stopping the flag from lying. It is the follow-up above,
  not a substitute for the refusal.

## Consequences
`--test-timeout-s 0` now exits 2 with a message that explains itself, and the only caller-controlled
path to a below-floor pytest budget is closed — `PROVISION_TIMEOUT_S` is a constant, not a flag.

SPEC §9's fixture would **not** have caught this — it mines clean at zero, so no existing test went
red — which is worth recording, because the fixture is this project's oracle for mining behaviour
and here it was fast enough to hide a defect. The guard that exists is at the CLI; the floor
beneath it is held by a docstring and by this record until the `tests/host/` test named above is
written.
