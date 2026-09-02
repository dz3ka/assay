"""The executable verdict (SPEC §4 tier 1): total over every report shape, and never lenient.

:func:`score_report` is the only rule that ever ranks a tool, so this file walks every shape a
trial can leave behind and demands a verdict for each - a shape without a verdict is a trial
that vanishes from the denominator, and the denominator is the honest half of the result
(CLAUDE.md). Reports are plain data and are built here directly, the way ``test_gate_rule``
builds them, which is legitimate precisely because they carry no behaviour.

Every branch below is ``FAILED``, except two. ``PASSED`` requires every recorded id - both
sets - present and passing; anything short of that, including "the evidence never arrived", is
a failure of the tool to solve the task, never a shrug. ``ERRORED`` is the one shape that is
nobody's verdict: an exit code pytest could not have produced, which is the harness having
failed to run the tests at all rather than the tool having failed to pass them - with one
code carved back out of that band, 137, which is the cgroup killing a trial that ate its own
ceiling and is therefore the tool's failure after all.
"""

import pytest

# TestReport and TestStatus are imported under other names on purpose: pytest tries to collect
# any module-level name starting with "Test", and warns about these two on every run if they
# are bound as they are spelled.
from assay.mine import TestReport as Report
from assay.mine import TestStatus as Status
from assay.results import Outcome
from assay.score import score_report
from assay.suite import Task

_TARGET = "tests/test_widget.py::test_target"
_GUARD = "tests/test_widget.py::test_guard"


def _task() -> Task:
    """A task as a suite on disk carries it: the two recorded sets are all that matters here."""
    return Task(
        schema_version=1,
        task_id="widget-fixture-000000000000",
        repo_url="https://example.invalid/widget.git",
        base_commit="0" * 40,
        test_files=("tests/test_widget.py",),
        test_patch="",
        ground_truth_patch="",
        fail_to_pass=(_TARGET,),
        pass_to_pass=(_GUARD,),
        prompt="make the target pass",
        metadata={},
    )


def _report(
    statuses: dict[str, Status],
    *,
    uncollectable: tuple[str, ...] = (),
    exit_code: int | None = None,
    timed_out: bool = False,
) -> Report:
    """A runner's report, exiting by default the way pytest would have on that result."""
    if exit_code is None:
        unhappy = any(status is not Status.PASSED for status in statuses.values())
        exit_code = 1 if unhappy or uncollectable else 0
    return Report(
        statuses=statuses,
        uncollectable=uncollectable,
        exit_code=exit_code,
        timed_out=timed_out,
    )


def test_a_report_where_every_recorded_test_passes_scores_passed() -> None:
    report = _report({_TARGET: Status.PASSED, _GUARD: Status.PASSED})

    assert score_report(_task(), report) is Outcome.PASSED


def test_no_report_at_all_scores_failed() -> None:
    # None is a trial with nothing measurable: the attempt diff did not apply, or the
    # workspace had no runner. Evidence that never arrived is not evidence of a pass.
    assert score_report(_task(), None) is Outcome.FAILED


def test_a_run_that_timed_out_scores_failed() -> None:
    report = _report({}, exit_code=-1, timed_out=True)

    assert score_report(_task(), report) is Outcome.FAILED


@pytest.mark.parametrize("exit_code", [1, 2, 3, 4, 5], ids=str)
def test_a_nonzero_pytest_exit_code_scores_failed_even_when_every_recorded_test_passed(
    exit_code: int,
) -> None:
    # The exit code can carry what the statuses cannot - an error outside any test, a crashed
    # plugin - so a run pytest itself called unhappy is not a pass, whatever the rows say.
    # Every code pytest documents is a statement about the run, so the whole 1-5 band is the
    # tool's verdict; the band's far side is asserted below and is not.
    report = _report({_TARGET: Status.PASSED, _GUARD: Status.PASSED}, exit_code=exit_code)

    assert score_report(_task(), report) is Outcome.FAILED


@pytest.mark.parametrize(
    "exit_code",
    [124, 125, 126, 127],
    ids=["unknown", "docker_client_failed", "not_executable", "not_found"],
)
def test_an_exit_code_outside_pytests_own_band_scores_errored(exit_code: int) -> None:
    """The defect this rule exists for: a harness failure must not be printed as a tool's zero.

    ``docker run`` answers 125 when the client or the daemon failed rather than the command -
    an image tag absent from this host is the everyday cause, one ``docker image prune`` away -
    and 126/127 when the command could not be invoked. Scored ``FAILED``, a pruned image would
    give every trial for that task a confident ``pass@1 = 0.0`` indistinguishable from a real
    failure, *including* the ground-truth adapter whose 1.0 brackets every real result.

    The statuses are deliberately all passing: the band is read before them, because a report
    whose exit code did not come from pytest says nothing trustworthy about its rows either.

    125 is the code ``tests/sandbox/test_runner.py`` measures a missing image producing, which
    is the other half of this chain. 124 stands for the rest of the band - a code nothing in
    this harness produces on purpose - and keeps the rule from reading as a list of three.
    """
    report = _report({_TARGET: Status.PASSED, _GUARD: Status.PASSED}, exit_code=exit_code)

    assert score_report(_task(), report) is Outcome.ERRORED


def test_a_run_killed_at_its_resource_ceiling_scores_failed() -> None:
    """137 is out of pytest's band and is still the tool's verdict: it spent what it was given.

    SIGKILL from the cgroup's OOM killer, measured in
    ``tests/sandbox/test_container_policy.py`` against a real container and a real limit. A
    tool that exhausted the memory or the CPU it was handed failed the trial - nothing about
    Assay malfunctioned - so calling this ``ERRORED`` would move a real failure out of the
    denominator and quietly flatter the tool that caused it.

    The statuses are all passing on purpose, as they are in the band test above: a container
    the kernel killed can still have written a junit report naming green rows before it died,
    and those rows are not a pass.
    """
    report = _report({_TARGET: Status.PASSED, _GUARD: Status.PASSED}, exit_code=137)

    assert score_report(_task(), report) is Outcome.FAILED


def test_a_timed_out_run_that_also_exited_137_is_still_read_as_the_timeout() -> None:
    """The resource-kill rule is read *after* ``timed_out``, and this pins what that must mean.

    Assay's own kill produces 137 at the docker layer too, so the two cases are one number
    apart at that seam. They are separated before the scorer sees them:
    :class:`assay.sandbox.SandboxTestRunner` and :class:`assay.host.PytestHostRunner` both
    convert a killed run into ``exit_code=-1`` with ``timed_out`` set, which is why a 137 that
    reaches here is necessarily a kill Assay did not send.

    The report below is the shape that would arrive if that conversion were ever dropped, and
    it must not become the resource-kill branch's problem. Both branches answer ``FAILED``, so
    this assertion cannot fail on placement alone - the observable half of the ordering is the
    test above, which fails outright if the rule is read after the band instead of before it.
    """
    report = _report({}, exit_code=137, timed_out=True)

    assert score_report(_task(), report) is Outcome.FAILED


def test_a_file_that_would_not_collect_scores_failed() -> None:
    report = _report(
        {_TARGET: Status.PASSED, _GUARD: Status.PASSED},
        uncollectable=("tests/test_other.py",),
        exit_code=0,
    )

    assert score_report(_task(), report) is Outcome.FAILED


def test_a_fail_to_pass_id_missing_from_the_report_scores_failed() -> None:
    # A run that never named the target test proved nothing about it, and "no evidence" must
    # not score the same as "proved to pass".
    report = _report({_GUARD: Status.PASSED}, exit_code=0)

    assert score_report(_task(), report) is Outcome.FAILED


@pytest.mark.parametrize(
    "status",
    [Status.FAILED, Status.ERRORED, Status.COLLECT_ERROR],
    ids=["failed", "errored", "collect_error"],
)
def test_a_fail_to_pass_id_that_did_not_pass_scores_failed(status: Status) -> None:
    report = _report({_TARGET: status, _GUARD: Status.PASSED}, exit_code=0)

    assert score_report(_task(), report) is Outcome.FAILED


def test_a_pass_to_pass_id_missing_from_the_report_scores_failed() -> None:
    report = _report({_TARGET: Status.PASSED}, exit_code=0)

    assert score_report(_task(), report) is Outcome.FAILED


def test_a_pass_to_pass_id_that_regressed_scores_failed() -> None:
    # The regression guard is half the executable signal (SPEC §4): a fix that breaks the
    # neighbouring tests did not solve the task, it moved it.
    report = _report({_TARGET: Status.PASSED, _GUARD: Status.FAILED}, exit_code=0)

    assert score_report(_task(), report) is Outcome.FAILED


def test_no_report_shape_scores_not_scored() -> None:
    # NOT_SCORED is SPEC §4's non-executable tiers, and those are M4+: in M2 every trial is
    # decided on executable signal, so a report is ranked, or it is the harness's own failure.
    shapes: list[Report | None] = [
        None,
        _report({_TARGET: Status.PASSED, _GUARD: Status.PASSED}),
        _report({}, exit_code=-1, timed_out=True),
        _report({}, exit_code=4),
        _report({}, exit_code=125),
        _report({}, exit_code=137),
        _report({}, exit_code=137, timed_out=True),
        _report({}, uncollectable=("tests/test_widget.py",)),
        _report({_TARGET: Status.COLLECT_ERROR}),
    ]

    for report in shapes:
        assert score_report(_task(), report) in {Outcome.PASSED, Outcome.FAILED, Outcome.ERRORED}
