"""The red->green gate: the rule that decides whether a commit is a task (SPEC §3).

SPEC §3 steps 3 and 4 are the whole trustworthiness story of a mined suite - the tests must be
*proved* to fail at the parent with only the test changes applied, and *proved* to pass once
the ground truth is applied. This module is that proof's arbiter and nothing else: it takes
the runs' reports as values and returns a verdict, so the rule can be exercised without git,
without pytest and without a clock (CLAUDE.md: mining and validation are pure functions over
explicit inputs).

The ground truth is run :data:`GREEN_CONFIRMATION_RUNS` times rather than once. Two agreeing
runs are the only thing in Assay that detects a flaky test, and a flaky test mined into a
suite is a task that scores tools at random - the failure mode this project exists to rule out
(SPEC §9 makes a flaky commit a required fixture).

The I/O that produces those reports - worktrees, patches, subprocesses - is ``run_gate``,
built on :mod:`assay.mine.protocols` and living outside this pure half.
"""

from collections.abc import Sequence
from typing import Final

from assay.mine.models import GateOutcome, GateRejection, NodeId, TestReport, TestStatus
from assay.suite import Task

# Two runs of the ground truth, compared. One run cannot distinguish "fixed" from "flaky",
# and each extra run costs a full test suite per candidate on a repository with thousands of
# commits, so this is the cheapest number that can detect disagreement at all.
GREEN_CONFIRMATION_RUNS: Final = 2

# The two exit codes that mean "nothing ran", and the reason both count as red.
#
# Measured with pytest 9.1.1. USAGE_ERROR (4): selecting a node id that does not resolve exits
# 4 and aborts the whole run before collecting anything - so a red run that reports no statuses
# at all and exits 4 is a run whose target tests do not exist at the parent commit. That is
# evidence of red (the commit *adds* them), not an assay bug, and reading it as a harness
# failure would discard the most common shape of a valid candidate. NO_TESTS_COLLECTED (5):
# an empty directory, a test file holding no tests, and a ``-k`` matching nothing all exit 5
# with a junit body byte-identical in shape to the exit-4 case - **the exit code is the only
# discriminator**, which is why the raw code travels in the report at all. Left unencoded, an
# exit-5 red falls through to ``already_green``: a conservative discard rather than a false
# accept, but one that costs yield for no reason a reader could reconstruct.
#
# Both are read only when the run reported no statuses whatsoever. A run that named even one
# test has evidence, and evidence outranks an exit code here.
_PYTEST_USAGE_ERROR: Final = 4
_PYTEST_NO_TESTS_COLLECTED: Final = 5
_NOTHING_RAN: Final = frozenset({_PYTEST_USAGE_ERROR, _PYTEST_NO_TESTS_COLLECTED})

# What two confirmation runs are compared on: their statuses, the files that would not
# collect, and the exit code.
type _RunSignature = tuple[tuple[tuple[NodeId, TestStatus], ...], tuple[str, ...], int]

_FAILING_STATUSES: Final = frozenset(
    {TestStatus.FAILED, TestStatus.ERRORED, TestStatus.COLLECT_ERROR}
)


def decide_gate(red: TestReport, greens: Sequence[TestReport]) -> GateOutcome:
    """Decide whether the evidence in these runs makes a task, or which discard it is.

    ``red`` is the run at the parent commit with only the test changes applied; ``greens`` are
    the :data:`GREEN_CONFIRMATION_RUNS` runs with the ground truth applied as well.

    The order of the checks is the order of SPEC §3, with one deliberate exception: two
    confirmation runs that disagree are reported as ``unstable_green`` before the pair is
    judged red or green at all, because a run that contradicts its twin is not evidence that
    the fix failed - filing it under ``still_red`` would put a flaky repository's whole yield
    under the wrong reason.

    Every unrecognised shape of evidence discards the candidate rather than accepting it. A
    lost candidate costs yield, which is reported; a wrongly minted task costs the suite's
    credibility, which is the product.

    Raises:
        ValueError: if ``greens`` does not hold exactly :data:`GREEN_CONFIRMATION_RUNS` runs.
            That is a caller that has not gathered the evidence this rule is defined over, not
            a property of the commit, so it is not one of the seven countable rejections.
    """
    if len(greens) != GREEN_CONFIRMATION_RUNS:
        raise ValueError(
            f"the gate needs exactly {GREEN_CONFIRMATION_RUNS} confirmation runs, got {len(greens)}"
        )

    if red.timed_out or any(green.timed_out for green in greens):
        return _rejected(GateRejection.RUN_TIMED_OUT)
    if not _shows_failure(red):
        return _rejected(GateRejection.ALREADY_GREEN)
    if len({_signature(green) for green in greens}) != 1:
        return _rejected(GateRejection.UNSTABLE_GREEN)
    confirmed = greens[0]
    if not _is_green(confirmed):
        return _rejected(GateRejection.STILL_RED)

    # The confirmation runs agree and are green, so they enumerate the tests that exist after
    # the fix. A test absent from the red run is one the commit added: it could not have
    # passed at the parent, which is the same evidence as an outright failure.
    passed_in_red = {
        node_id for node_id, status in red.statuses.items() if status is TestStatus.PASSED
    }
    fail_to_pass = tuple(sorted(set(confirmed.statuses) - passed_in_red))
    pass_to_pass = tuple(sorted(set(confirmed.statuses) & passed_in_red))
    if not fail_to_pass:
        # Red was red and green is green, but nothing crossed between them - the failing test
        # was deleted rather than fixed. A task with no fail_to_pass has no gate to score.
        return _rejected(GateRejection.STILL_RED)
    return GateOutcome(rejection=None, fail_to_pass=fail_to_pass, pass_to_pass=pass_to_pass)


def revalidates(task: Task, outcome: GateOutcome | None) -> bool:
    """Whether re-running the gate reproduced the sets ``task`` records - ``assay validate``.

    An accepting outcome is not enough. The gate accepts on whatever crosses red to green
    *now*, which need not be what the suite wrote down: a dependency update that makes one
    recorded ``fail_to_pass`` test pass at the base state, while another test from the same
    patch still crosses, is accepted by :func:`decide_gate` with a different set. Scoring
    afterwards gates on the *task's* sets, so calling that task valid would leave a suite whose
    null adapter passes - and the null adapter bracketing every real result at zero is a
    CLAUDE.md non-negotiable. Revalidating therefore means reproducing both recorded sets.

    An outcome of ``None`` - a workspace that could not be provisioned - is not valid either.
    A suite that cannot be re-proved is not a suite that has been re-proved, and ``assay
    validate`` exits 1 on it. The CLI may format the difference between "invalid" and "could
    not be checked"; it may not decide validity, which is why the rule is here beside
    :func:`decide_gate` and testable on hand-built values in the same way.

    Sets rather than tuples: both sides are already sorted by :func:`decide_gate`, so the
    comparison is order-insensitive by construction and says so.

    Rejected alternative: requiring only that the recorded ``fail_to_pass`` still crosses. That
    accepts silent erosion of ``pass_to_pass`` - a regression guard the suite claims and no
    longer has - which is the same overstatement in the other set.
    """
    if outcome is None or outcome.rejection is not None:
        return False
    return set(outcome.fail_to_pass) == set(task.fail_to_pass) and set(outcome.pass_to_pass) == set(
        task.pass_to_pass
    )


def _rejected(rejection: GateRejection) -> GateOutcome:
    return GateOutcome(rejection=rejection, fail_to_pass=(), pass_to_pass=())


def _shows_failure(red: TestReport) -> bool:
    """Whether the red run demonstrated a failure - SPEC §3 step 3, and nothing weaker.

    Three shapes count, and they are all the same claim in different vocabulary: a test that
    failed, a file that would not collect, or a selection that ran nothing at all.
    """
    if any(status in _FAILING_STATUSES for status in red.statuses.values()):
        return True
    if red.uncollectable:
        return True
    return red.exit_code in _NOTHING_RAN and not red.statuses


def _is_green(green: TestReport) -> bool:
    """Whether a confirmation run proved the suite green - SPEC §3 step 4.

    A clean exit code is required on top of the statuses: an interrupted run reports the tests
    it got through as passed and says nothing about the rest, and reading that as green would
    mint a task on half a suite.
    """
    if green.exit_code != 0 or green.uncollectable:
        return False
    return all(status is TestStatus.PASSED for status in green.statuses.values())


def _signature(report: TestReport) -> _RunSignature:
    """What two confirmation runs have to agree on to count as one repeated observation.

    Statuses, the files that would not collect, and the exit code. Anything that differs
    between two runs of the same tree is non-determinism, whichever field it surfaces in.
    """
    return (tuple(sorted(report.statuses.items())), report.uncollectable, report.exit_code)
