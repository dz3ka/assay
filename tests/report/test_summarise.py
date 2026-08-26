"""Turning recorded trials into the numbers a report prints - and what those numbers mean.

Every expected value here is computed by hand and written as a literal (CLAUDE.md): a test
that recomputed pass@1 the way the code does would agree with any arithmetic, including the
wrong one. The two fixtures are the ones the renderers will be accepted against, so their
numbers are asserted here first, where the derivation is the subject rather than the layout.

Two of these tests pin behaviour that looks like a gap and is not. A repeated
``(task_id, adapter_name, trial_index)`` triple counts as another trial rather than raising,
and an ``errored`` trial stays in the denominator - both are M4 aggregation decisions
(SPEC §7), and quietly deciding either one here would change a published number.
"""

from decimal import Decimal
from pathlib import Path

from assay.report import (
    STUB_INTERVAL_NOTICE,
    Interval,
    VerdictReason,
    build_report,
    summarise,
)
from assay.results import Attempt, Outcome, Result, ResultSet, read_result_set

FIXTURES = Path(__file__).parent.parent / "fixtures"

SUITE_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


def _result(task_id: str, adapter_name: str, trial_index: int, outcome: Outcome) -> Result:
    """A result carrying nothing but the four fields a summary is derived from."""
    return Result(
        schema_version=1,
        task_id=task_id,
        adapter_name=adapter_name,
        trial_index=trial_index,
        attempt=Attempt(
            schema_version=1,
            adapter_name=adapter_name,
            adapter_version="0.1.0",
            task_id=task_id,
            trial_index=trial_index,
            diff="",
            input_tokens=0,
            output_tokens=0,
            wall_clock_ms=0,
            tool_calls=0,
            retries=0,
            cost_usd=Decimal("0.000000"),
            error=None,
        ),
        outcome=outcome,
    )


def _result_set(*results: Result) -> ResultSet:
    return ResultSet(schema_version=1, suite_hash=SUITE_HASH, results=results)


def test_the_disjoint_fixture_scores_the_bracket_every_report_carries() -> None:
    # 2 tasks x 2 trials each: null fails all four, ground-truth passes all four. The floor
    # and the ceiling every real result is read against (CLAUDE.md).
    null, ground_truth = summarise(read_result_set(FIXTURES / "results_disjoint.json"))

    assert null.tool == "null"
    assert null.trials == 4
    assert null.pass_at_1 == 0.0
    assert null.pass_caret_n == 0.0
    assert null.pass_caret_n_interval == Interval(low=0.0, high=0.25)

    assert ground_truth.tool == "ground-truth"
    assert ground_truth.trials == 4
    assert ground_truth.pass_at_1 == 1.0
    assert ground_truth.pass_caret_n == 1.0
    assert ground_truth.pass_caret_n_interval == Interval(low=0.75, high=1.0)


def test_the_overlapping_fixture_scores_two_tools_the_data_cannot_separate() -> None:
    # alpha: three tasks clean, one task 1-of-2. pass@1 = mean(1, 1, 1, 0.5) = 0.875,
    # pass^n = 3/4. beta: two clean, one 1-of-2, one 0-of-2. pass@1 = mean(1, 1, 0.5, 0)
    # = 0.625, pass^n = 2/4. Every value is dyadic, so the floats are exact.
    alpha, beta = summarise(read_result_set(FIXTURES / "results_overlapping.json"))

    assert alpha.tool == "alpha"
    assert alpha.trials == 8
    assert alpha.pass_at_1 == 0.875
    assert alpha.pass_caret_n == 0.75
    assert alpha.pass_caret_n_interval == Interval(low=0.5, high=1.0)

    assert beta.tool == "beta"
    assert beta.trials == 8
    assert beta.pass_at_1 == 0.625
    assert beta.pass_caret_n == 0.5
    assert beta.pass_caret_n_interval == Interval(low=0.25, high=0.75)


def test_pass_at_1_is_a_mean_over_tasks_not_over_pooled_trials() -> None:
    # One task run three times and failed twice, another run once and passed. Pooled, that
    # is 2/4 = 0.5; per task it is mean(1/3, 1) = 2/3, and the task run more often must not
    # get more of the vote.
    result_set = _result_set(
        _result("t1", "alpha", 0, Outcome.PASSED),
        _result("t1", "alpha", 1, Outcome.FAILED),
        _result("t1", "alpha", 2, Outcome.FAILED),
        _result("t2", "alpha", 0, Outcome.PASSED),
    )

    (alpha,) = summarise(result_set)

    assert alpha.trials == 4
    assert alpha.pass_at_1 == (1 / 3 + 1.0) / 2
    assert alpha.pass_caret_n == 0.5


def test_a_repeated_trial_triple_counts_as_one_more_trial() -> None:
    # The store accepts a duplicate (SPEC §7 leaves collapsing to M4), so the summary counts
    # it rather than raising or silently dropping a measurement.
    result_set = _result_set(
        _result("t1", "alpha", 0, Outcome.PASSED),
        _result("t1", "alpha", 1, Outcome.FAILED),
        _result("t1", "alpha", 1, Outcome.FAILED),
    )

    (alpha,) = summarise(result_set)

    assert alpha.trials == 3
    assert alpha.pass_at_1 == 1 / 3
    assert alpha.pass_caret_n == 0.0


def test_an_errored_trial_is_not_a_pass_and_is_not_excluded() -> None:
    # A tool whose harness fell over on every trial scores zero, not "no data": excluding
    # errors from the denominator would flatter the tool that crashes most.
    result_set = _result_set(
        _result("t1", "alpha", 0, Outcome.ERRORED),
        _result("t1", "alpha", 1, Outcome.ERRORED),
        _result("t2", "alpha", 0, Outcome.ERRORED),
    )

    (alpha,) = summarise(result_set)

    assert alpha.trials == 3
    assert alpha.pass_at_1 == 0.0
    assert alpha.pass_caret_n == 0.0


def test_a_not_scored_trial_is_not_a_pass_either() -> None:
    result_set = _result_set(
        _result("t1", "alpha", 0, Outcome.NOT_SCORED),
        _result("t1", "alpha", 1, Outcome.PASSED),
    )

    (alpha,) = summarise(result_set)

    assert alpha.trials == 2
    assert alpha.pass_at_1 == 0.5
    assert alpha.pass_caret_n == 0.0


def test_a_result_set_with_no_results_summarises_to_no_tools() -> None:
    assert summarise(_result_set()) == ()


def test_tools_are_ordered_by_first_appearance() -> None:
    # Not sorted: a report's column order is the order the run recorded, so a renderer's
    # table matches the file it was rendered from.
    result_set = _result_set(
        _result("t1", "zulu", 0, Outcome.PASSED),
        _result("t1", "alpha", 0, Outcome.PASSED),
        _result("t2", "zulu", 0, Outcome.PASSED),
        _result("t2", "mike", 0, Outcome.FAILED),
    )

    assert [summary.tool for summary in summarise(result_set)] == ["zulu", "alpha", "mike"]


def test_the_stub_interval_is_clamped_to_the_unit_interval() -> None:
    # +/-0.25 around 0.0 and around 1.0 would run outside [0, 1], which Interval refuses;
    # the band is clamped rather than the model relaxed.
    result_set = _result_set(
        _result("t1", "floor", 0, Outcome.FAILED),
        _result("t1", "ceiling", 0, Outcome.PASSED),
    )

    floor, ceiling = summarise(result_set)

    assert floor.pass_caret_n_interval == Interval(low=0.0, high=0.25)
    assert ceiling.pass_caret_n_interval == Interval(low=0.75, high=1.0)


def test_the_stub_notice_says_the_intervals_are_not_measured() -> None:
    # The notice is printed to a Windows console, so it is ASCII, and it has to name the
    # placeholder as one - a renderer that showed a stub band without it would publish an
    # uncertainty nobody measured.
    assert STUB_INTERVAL_NOTICE.isascii()
    assert "PLACEHOLDER" in STUB_INTERVAL_NOTICE
    assert "0.25" in STUB_INTERVAL_NOTICE
    assert "M4" in STUB_INTERVAL_NOTICE


def test_the_disjoint_fixture_reports_a_winner() -> None:
    result_set = read_result_set(FIXTURES / "results_disjoint.json")

    report = build_report(result_set, summarise(result_set))

    (comparison,) = report.comparisons
    assert comparison.verdict.winner == "ground-truth"
    assert comparison.verdict.reason is VerdictReason.INTERVALS_DISJOINT


def test_the_overlapping_fixture_reports_no_winner() -> None:
    # alpha leads beta on both point estimates and still wins nothing: the intervals share
    # [0.5, 0.75], so the run has not told the two apart (SPEC §4).
    result_set = read_result_set(FIXTURES / "results_overlapping.json")

    report = build_report(result_set, summarise(result_set))

    (comparison,) = report.comparisons
    assert comparison.verdict.winner is None
    assert comparison.verdict.reason is VerdictReason.INTERVALS_OVERLAP
