"""The red->green gate rule (SPEC §3), decided on evidence and nothing else.

:func:`decide_gate` is the whole trustworthiness story of a mined suite, so it is a pure
function over :class:`TestReport` values and this file is its only witness: reports are plain
data and are built here directly, which is legitimate precisely because they carry no
behaviour. The fixture git repository that proves the *reports* are real is a separate
deliverable (SPEC §9), and no hand-rolled fake of git or of pytest appears here - a fake would
only prove that the rule agrees with an assumption about tools neither of which was consulted.

Every branch below is a discard, except one. That is the point: most candidates fail, the
failures are counted by reason, and the yield is the number the project reports.
"""

import pytest

# TestReport and TestStatus are imported under other names on purpose: pytest tries to collect
# any module-level name starting with "Test", and warns about these two on every run if they
# are bound as they are spelled.
from assay.mine import GREEN_CONFIRMATION_RUNS, GateRejection, decide_gate
from assay.mine import TestReport as Report
from assay.mine import TestStatus as Status

_TARGET = "tests/test_parser.py::test_header"
_NEIGHBOUR = "tests/test_parser.py::test_body"


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


def _greens(statuses: dict[str, Status] | None = None) -> list[Report]:
    passing = statuses or {_TARGET: Status.PASSED, _NEIGHBOUR: Status.PASSED}
    return [_report(dict(passing)) for _ in range(GREEN_CONFIRMATION_RUNS)]


def test_a_commit_whose_tests_go_red_to_green_is_accepted() -> None:
    red = _report({_TARGET: Status.FAILED, _NEIGHBOUR: Status.PASSED})

    outcome = decide_gate(red, _greens())

    assert outcome.rejection is None
    assert outcome.fail_to_pass == (_TARGET,)
    assert outcome.pass_to_pass == (_NEIGHBOUR,)


def test_a_test_that_could_not_be_collected_at_the_parent_counts_as_red() -> None:
    # The ordinary shape of a new test: its module imports something the fix adds, so at the
    # parent it does not fail - it does not even load.
    red = _report({_TARGET: Status.COLLECT_ERROR, _NEIGHBOUR: Status.PASSED})

    outcome = decide_gate(red, _greens())

    assert outcome.rejection is None
    assert outcome.fail_to_pass == (_TARGET,)


def test_a_usage_error_that_collected_nothing_counts_as_red() -> None:
    # Measured with pytest 8: selecting a node id that does not resolve exits 4 and aborts
    # the whole run before anything is collected. At the parent commit that is exactly what
    # a test the commit *adds* looks like, so it is evidence of red, not a harness bug.
    red = _report({}, exit_code=4)

    outcome = decide_gate(red, _greens())

    assert outcome.rejection is None
    assert outcome.fail_to_pass == (_NEIGHBOUR, _TARGET)
    assert outcome.pass_to_pass == ()


def test_a_file_that_would_not_import_at_the_parent_counts_as_red() -> None:
    red = _report({}, uncollectable=("tests/test_parser.py",))

    assert decide_gate(red, _greens()).rejection is None


def test_a_commit_whose_tests_already_pass_is_rejected() -> None:
    red = _report({_TARGET: Status.PASSED, _NEIGHBOUR: Status.PASSED})

    outcome = decide_gate(red, _greens())

    assert outcome.rejection is GateRejection.ALREADY_GREEN
    assert outcome.fail_to_pass == ()
    assert outcome.pass_to_pass == ()


def test_a_commit_whose_ground_truth_does_not_fix_the_tests_is_rejected() -> None:
    red = _report({_TARGET: Status.FAILED})
    greens = [_report({_TARGET: Status.FAILED}) for _ in range(GREEN_CONFIRMATION_RUNS)]

    assert decide_gate(red, greens).rejection is GateRejection.STILL_RED


def test_two_confirmation_runs_that_disagree_reject_the_commit_as_flaky() -> None:
    # This is the only thing in Assay that detects a flaky test, and it is why the ground
    # truth is run twice rather than once (SPEC §9's flaky-commit fixture).
    red = _report({_TARGET: Status.FAILED})
    greens = [_report({_TARGET: Status.PASSED}), _report({_TARGET: Status.FAILED})]

    assert decide_gate(red, greens).rejection is GateRejection.UNSTABLE_GREEN


def test_a_flaky_test_is_reported_as_flaky_rather_than_as_still_red() -> None:
    # Order matters: a run that disagrees with its twin is not evidence the fix failed, and
    # calling it still_red would file a flaky repository's whole yield under the wrong reason.
    red = _report({_TARGET: Status.FAILED, _NEIGHBOUR: Status.PASSED})
    greens = [
        _report({_TARGET: Status.FAILED, _NEIGHBOUR: Status.PASSED}),
        _report({_TARGET: Status.PASSED, _NEIGHBOUR: Status.PASSED}),
    ]

    assert decide_gate(red, greens).rejection is GateRejection.UNSTABLE_GREEN


def test_confirmation_runs_that_collected_different_tests_disagree() -> None:
    red = _report({_TARGET: Status.FAILED})
    greens = [
        _report({_TARGET: Status.PASSED}),
        _report({_TARGET: Status.PASSED, _NEIGHBOUR: Status.PASSED}),
    ]

    assert decide_gate(red, greens).rejection is GateRejection.UNSTABLE_GREEN


@pytest.mark.parametrize(
    "slow_run",
    ["red", "first-green", "second-green"],
    ids=["red", "first-green", "second-green"],
)
def test_a_run_that_ran_out_of_time_decides_nothing(slow_run: str) -> None:
    red = _report({_TARGET: Status.FAILED}, timed_out=slow_run == "red")
    greens = [
        _report({_TARGET: Status.PASSED}, timed_out=slow_run == "first-green"),
        _report({_TARGET: Status.PASSED}, timed_out=slow_run == "second-green"),
    ]

    assert decide_gate(red, greens).rejection is GateRejection.RUN_TIMED_OUT


def test_a_confirmation_run_that_did_not_exit_cleanly_is_not_evidence_of_green() -> None:
    # An interrupted run reports the tests it got through as passed and says nothing about
    # the rest; reading that as green would mint a task on half a suite.
    red = _report({_TARGET: Status.FAILED})
    greens = [_report({_TARGET: Status.PASSED}, exit_code=2) for _ in range(2)]

    assert decide_gate(red, greens).rejection is GateRejection.STILL_RED


def test_a_candidate_whose_tests_never_ran_at_all_is_not_reported_as_still_red() -> None:
    # The split ADR-0017 deferred to M2. Exit 4 with no statuses and nothing uncollectable is
    # "no test ran", not "the fix did not work": the two are opposite claims about a
    # repository, and merging them made a `still_red` tally unusable as evidence about one.
    # Both ends have to say it - see the discrimination cases below.
    red = _report({}, exit_code=4)
    greens = [_report({}, exit_code=4) for _ in range(GREEN_CONFIRMATION_RUNS)]

    outcome = decide_gate(red, greens)

    assert outcome.rejection is GateRejection.NO_TESTS_EXECUTED
    assert outcome.fail_to_pass == ()
    assert outcome.pass_to_pass == ()


def test_a_selection_that_resolved_to_nothing_at_both_ends_also_ran_no_test() -> None:
    # Exit 5 - the selection collected nothing at all - is the other half of `_NOTHING_RAN`,
    # and it is the same non-evidence as exit 4 once both ends agree on it.
    red = _report({}, exit_code=5)
    greens = [_report({}, exit_code=5) for _ in range(GREEN_CONFIRMATION_RUNS)]

    assert decide_gate(red, greens).rejection is GateRejection.NO_TESTS_EXECUTED


def test_a_green_run_that_really_failed_is_still_red_however_the_red_run_ended() -> None:
    # The discrimination that keeps the new reason honest: the confirmation runs executed the
    # tests and they failed, so the fix demonstrably did not work. Charging that to
    # `no_tests_executed` because the *red* run happened to run nothing would understate the
    # gate's most important discard.
    red = _report({}, exit_code=4)
    greens = [_report({_TARGET: Status.FAILED}) for _ in range(GREEN_CONFIRMATION_RUNS)]

    assert decide_gate(red, greens).rejection is GateRejection.STILL_RED


def test_a_red_run_with_real_evidence_is_still_red_when_the_green_runs_go_quiet() -> None:
    # And the other direction: red named a failing test, so something was measurable at the
    # parent. A confirmation run that then ran nothing is a broken run, not proof that the
    # candidate was never testable - the reason exists for candidates nothing could be
    # learned about at all.
    red = _report({_TARGET: Status.FAILED})
    greens = [_report({}, exit_code=4) for _ in range(GREEN_CONFIRMATION_RUNS)]

    assert decide_gate(red, greens).rejection is GateRejection.STILL_RED


def test_a_file_that_would_not_collect_is_evidence_rather_than_silence() -> None:
    # `uncollectable` is a module that failed to import - a run that got far enough to say
    # something about a named file. That is the collect-error shape, and it is exactly what
    # the httpie record insists must not be described as "nothing ran" (ADR-0017).
    red = _report({}, uncollectable=("tests/test_parser.py",), exit_code=4)
    greens = [
        _report({}, uncollectable=("tests/test_parser.py",), exit_code=4)
        for _ in range(GREEN_CONFIRMATION_RUNS)
    ]

    assert decide_gate(red, greens).rejection is GateRejection.STILL_RED


def test_a_run_that_proved_no_test_turned_green_is_rejected() -> None:
    # The commit deleted the failing test rather than fixing it: red was genuinely red and
    # the confirmation runs are genuinely green, but nothing crossed from one to the other,
    # and a task with no fail_to_pass has no gate left to score anything against.
    red = _report({_TARGET: Status.FAILED, _NEIGHBOUR: Status.PASSED})
    greens = [_report({_NEIGHBOUR: Status.PASSED}) for _ in range(GREEN_CONFIRMATION_RUNS)]

    assert decide_gate(red, greens).rejection is GateRejection.STILL_RED


def test_the_accepted_sets_are_sorted_so_one_commit_mints_one_task() -> None:
    # Both tuples land in a content-addressed Task, so their order cannot depend on the
    # order a runner happened to report its results in.
    red = _report({"b.py::t": Status.FAILED, "a.py::t": Status.FAILED})
    greens = [
        _report({"b.py::t": Status.PASSED, "a.py::t": Status.PASSED}),
        _report({"a.py::t": Status.PASSED, "b.py::t": Status.PASSED}),
    ]

    assert decide_gate(red, greens).fail_to_pass == ("a.py::t", "b.py::t")


@pytest.mark.parametrize("count", [0, 1, 3], ids=["none", "one", "three"])
def test_the_rule_refuses_to_decide_on_the_wrong_number_of_confirmation_runs(count: int) -> None:
    # Not a rejection: a caller that ran the ground truth once has not gathered the evidence
    # the rule is defined over, and answering anyway would report a flake as a task.
    red = _report({_TARGET: Status.FAILED})
    greens = [_report({_TARGET: Status.PASSED}) for _ in range(count)]

    with pytest.raises(ValueError, match="confirmation"):
        decide_gate(red, greens)
