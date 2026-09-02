"""The executable verdict: SPEC §4 tier 1, the only signal a tool is ever ranked on.

One trial's verdict is decided here, on the runner's report and nothing else - no judge, no
diff distance, no partial credit. Those tiers exist (SPEC §4 lists four) and land in M4+; in
M2 every trial is decided on executable signal, so ``NOT_SCORED`` is never returned.

``ERRORED`` is returned for exactly one shape: an exit code pytest could not have produced.
That is the harness having failed to run the tests rather than the tool having failed to pass
them, and the two must not print the same number. The *other* half of ``ERRORED`` stays with
:func:`assay.score.run_trial`, which knows whether an adapter failed before any report could
exist; this half is the one only a report can show.

Pure in the stronger sense :mod:`assay.mine.gate` is pure: a function over values, total
over every shape a trial can leave behind, raising nothing. A verdict that can fail to be
reached is a trial that vanishes from the denominator, and the denominator is the honest
half of the result (CLAUDE.md, "report yield, not just totals").
"""

from typing import Final

from assay.mine.models import TestReport, TestStatus
from assay.results import Outcome
from assay.suite import Task

# Every exit code pytest documents: 0 all passed, 1 tests failed, 2 interrupted, 3 internal
# error, 4 usage error, 5 no tests collected. The set is closed, which is what makes its
# complement readable - a code outside it did not come from pytest, so whatever produced it was
# not answering a question about the tests.
_PYTEST_EXIT_CODES: Final = frozenset(range(6))

# SIGKILL from the cgroup ceiling; see :class:`assay.sandbox.ContainerLimits`. 128 + 9, the shell
# convention docker reports a killed container's status with. Out of pytest's band, and still the
# tool's own failure rather than the harness's - the one carve-out from the rule above.
_RESOURCE_KILL_EXIT_CODE: Final = 137


def score_report(task: Task, report: TestReport | None) -> Outcome:
    """Decide one trial's executable verdict from the evidence a test run left behind.

    ``PASSED`` requires every id the task recorded - both ``fail_to_pass`` and
    ``pass_to_pass`` - present in the report and :attr:`TestStatus.PASSED`. Present *and*
    passing, because a run that never named a test proved nothing about it, and "no
    evidence" must not score the same as "proved to pass" - the exact leniency the
    red->green gate exists to rule out on the mining side.

    Everything else is ``FAILED``, including the shapes where no evidence could exist at
    all: ``None`` (the attempt diff did not apply, or the workspace had no runner), a run
    killed at its budget, a nonzero pytest exit code, a file that would not collect. Each of
    those is the tool failing to leave the workspace in a measurable passing state, which is
    the thing being scored - not a shrug, and not the harness erroring.

    ``ERRORED`` is the one exception, and it is the code band that says so. Pytest's own
    codes are 0 to 5 and nothing else; a report carrying anything outside them was produced
    by something that was not pytest answering. ``docker run`` is the case in hand: it
    answers 125 when the client or the daemon failed rather than the command - an image tag
    absent from this host, one ``docker image prune`` away - and 126 or 127 when the command
    could not be invoked. Called ``FAILED``, that would print a confident zero for a run
    that never happened, and it would do so for the ground-truth adapter as readily as for a
    tool, silently removing the top of the bracket every real result is read against.

    The band is read *here*, on the report, rather than at the sandbox seam.
    :func:`assay.sandbox.run_in_sandbox` runs whatever argv it is handed - probes as well as
    pytest - so it has no standing to call 137 a fault, and a runner that raised instead of
    reporting would end a walk the ``TestRunner`` protocol requires it to let continue. This
    function is the one place that knows the report came from a pytest run *and* is free to
    say so in the verdict rather than in an exception.

    One code is carved back out of the band: 137, SIGKILL, which is a container killed at the
    cgroup ceiling :class:`assay.sandbox.ContainerLimits` set for it. That is not an ambiguous
    client failure - it is a specific, measured outcome attributable to the trial, which spent
    the memory or the CPU it was given and did not finish. A tool that exhausts its budget
    failed; nothing about Assay malfunctioned, and scoring it ``ERRORED`` would lift a real
    failure out of the denominator (``tests/sandbox/test_container_policy.py`` provokes exactly
    this kill and reads the verdict off the container's own exit code).

    Order matters three times, and 137 is why the middle one is load-bearing. ``timed_out`` is
    read first, because a killed run carries a sentinel code that is out of band by
    construction and is still the tool's failure to finish inside its budget - and because
    *Assay's own* kill also produces 137 at the docker layer. It never arrives here wearing
    that number: :class:`assay.sandbox.SandboxTestRunner` and
    :class:`assay.host.PytestHostRunner` both convert a run they killed into ``exit_code=-1``
    with ``timed_out`` set, so a surviving 137 is necessarily a kill Assay did not send. The
    resource-kill code is read next, before the band, because the band would otherwise answer
    ``ERRORED`` first and the rule would never run at all. The band is then read before the
    statuses, because rows from a run pytest did not finish reporting on are not rows to rank a
    tool by.
    """
    if report is None:
        return Outcome.FAILED
    if report.timed_out:
        return Outcome.FAILED
    if report.exit_code == _RESOURCE_KILL_EXIT_CODE:
        return Outcome.FAILED
    if report.exit_code not in _PYTEST_EXIT_CODES:
        return Outcome.ERRORED
    # The exit code can carry what the statuses cannot - an error outside any test, a
    # crashed plugin - so a run pytest itself called unhappy is not a pass, whatever the
    # rows say. Same for a file that produced no rows because it never collected.
    if report.exit_code != 0:
        return Outcome.FAILED
    if report.uncollectable:
        return Outcome.FAILED
    recorded = (*task.fail_to_pass, *task.pass_to_pass)
    if all(report.statuses.get(node) is TestStatus.PASSED for node in recorded):
        return Outcome.PASSED
    return Outcome.FAILED
