"""Turning recorded trials into the numbers a report prints - and what those numbers mean.

Every expected value here is computed by hand and written as a literal (CLAUDE.md): a test
that recomputed pass@1 the way the code does would agree with any arithmetic, including the
wrong one. The two fixtures are the ones the renderers will be accepted against, so their
numbers are asserted here first, where the derivation is the subject rather than the layout.

The two bands come from two instruments. pass^n gets a Wilson interval over *tasks*
(ADR-0035) and pass@1 gets a seeded percentile bootstrap over the same tasks (ADR-0043),
and both arithmetics are checked against hand-computed values in ``tests/stats/``. What is
asserted here is the part that arithmetic cannot check: which numbers go into each band, and
that the paired test between two tools reads the tasks they were *both* given.

The paired p-value is the one number in this file that is not allowed to change a decision.
``test_a_significant_paired_p_still_names_no_winner`` is the tripwire: a p below 0.05 sitting
beside "no winner" is the intended output, not a bug (ADR-0044).

Two of these tests pin behaviour that looks like a gap and is not. A repeated
``(task_id, adapter_name, trial_index)`` triple counts as another trial rather than raising,
and an ``errored`` trial stays in the denominator - both are M4 aggregation decisions
(SPEC §7), and quietly deciding either one here would change a published number.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from assay.report import (
    CostBasis,
    CostOutOfRangeError,
    PriceTable,
    ToolPrice,
    ToolSummary,
    VerdictReason,
    build_report,
    format_paired,
    summarise,
)
from assay.results import Attempt, Outcome, Result, ResultSet, read_result_set

FIXTURES = Path(__file__).parent.parent / "fixtures"

# Wilson bands are irrational; the literals below are quoted to ten decimal places and the
# arithmetic is checked against hand-computed values in ``tests/stats/test_wilson.py``. Here
# the subject is which numbers go *into* the band, so the endpoints are compared at that width
# rather than by exact float equality.
_PLACES = 10

SUITE_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


def _result(
    task_id: str,
    adapter_name: str,
    trial_index: int,
    outcome: Outcome,
    tokens: tuple[int, int] = (0, 0),
) -> Result:
    """A result carrying the four fields a summary is derived from, and what the trial spent.

    ``tokens`` defaults to none recorded, which is what every adapter Assay ships writes today
    and therefore what most of these fixtures should look like. The cost tests are the ones
    that hand it something else.
    """
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
            input_tokens=tokens[0],
            output_tokens=tokens[1],
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


def _one_trial_each(tasks: tuple[str, ...], solved: dict[str, set[str]]) -> ResultSet:
    """One trial per tool per task, passing exactly where ``solved`` says the tool solved it.

    Every tool is run on every task, so the pairing the paired test needs is total: what varies
    between the tools is which tasks they got right, not which tasks they were given.
    """
    return _result_set(
        *(
            _result(task, tool, 0, Outcome.PASSED if task in tool_solved else Outcome.FAILED)
            for task in tasks
            for tool, tool_solved in solved.items()
        )
    )


def _band(summary: ToolSummary) -> tuple[float, float]:
    """One tool's pass^n interval, at the width the literals here are written to."""
    interval = summary.pass_caret_n_interval
    return round(interval.low, _PLACES), round(interval.high, _PLACES)


def _pass_at_1_band(summary: ToolSummary) -> tuple[float, float]:
    """One tool's pass@1 interval - the bootstrap band, not the Wilson one."""
    interval = summary.pass_at_1_interval
    return interval.low, interval.high


def test_the_disjoint_fixture_scores_the_bracket_every_report_carries() -> None:
    # 5 tasks x 2 trials each: null fails all ten, ground-truth passes all ten. The floor and
    # the ceiling every real result is read against (CLAUDE.md).
    #
    # Five tasks, not two, because the interval is a Wilson band over *tasks* (ADR-0035): the
    # bracket separates only when n > z^2 = 3.8415, so four tasks is the minimum and two - what
    # this fixture held while the band was an invented +/-0.25 - is not enough evidence to
    # declare even a perfect tool the winner. The bands are 0/5 and 5/5 from
    # ``tests/stats/test_wilson.py``.
    null, ground_truth = summarise(read_result_set(FIXTURES / "results_disjoint.json"))

    assert null.tool == "null"
    assert null.trials == 10
    assert null.pass_at_1 == 0.0
    assert null.pass_caret_n == 0.0
    assert _band(null) == (0.0, 0.4344824648)

    assert ground_truth.tool == "ground-truth"
    assert ground_truth.trials == 10
    assert ground_truth.pass_at_1 == 1.0
    assert ground_truth.pass_caret_n == 1.0
    assert _band(ground_truth) == (0.5655175352, 1.0)


def test_the_overlapping_fixture_scores_two_tools_the_data_cannot_separate() -> None:
    # alpha: three tasks clean, one task 1-of-2. pass@1 = mean(1, 1, 1, 0.5) = 0.875,
    # pass^n = 3/4. beta: two clean, one 1-of-2, one 0-of-2. pass@1 = mean(1, 1, 0.5, 0)
    # = 0.625, pass^n = 2/4. Every point estimate is dyadic, so those floats are exact.
    #
    # The bands are Wilson over 4 tasks. alpha, k=3: centre = (3 + 1.9207294103)/7.8414588207
    # = 0.6275272909, half = (1.959963984540054/7.8414588207) * sqrt(3*1/4 + 0.9603647052)
    # = 0.2499487142 * 1.3078093383 = 0.3268854483. beta, k=2: centre = 0.5 exactly,
    # half = 0.2499487142 * sqrt(2*2/4 + 0.9603647052) = 0.2499487142 * 1.4001302798
    # = 0.3499610108.
    alpha, beta = summarise(read_result_set(FIXTURES / "results_overlapping.json"))

    assert alpha.tool == "alpha"
    assert alpha.trials == 8
    assert alpha.pass_at_1 == 0.875
    assert alpha.pass_caret_n == 0.75
    assert _band(alpha) == (0.3006418426, 0.9544127392)

    assert beta.tool == "beta"
    assert beta.trials == 8
    assert beta.pass_at_1 == 0.625
    assert beta.pass_caret_n == 0.5
    assert _band(beta) == (0.1500389892, 0.8499610108)


def test_the_interval_counts_tasks_not_trials() -> None:
    # ADR-0035: pass^n is the fraction of *tasks* every trial of which passed, so the band's
    # denominator is the task count. One task run eight times is one observation, not eight -
    # a harness that fed the trial count to Wilson would narrow its interval by rerunning the
    # same task, which is the cheapest way to fake confidence in this whole codebase.
    trials = tuple(_result("t1", "alpha", index, Outcome.PASSED) for index in range(8))

    (alpha,) = summarise(_result_set(*trials))

    assert alpha.trials == 8
    assert alpha.pass_caret_n == 1.0
    # 1/1, not 8/8: centre = (1 + 1.9207294103)/4.8414588207 = 0.6032746572, half =
    # (1.959963984540054/4.8414588207) * sqrt(0 + 0.9603647052) = 0.4048292172 * 0.9799819923
    # = 0.3967253428, and the top end clamps to 1.
    assert _band(alpha) == (0.2065493144, 1.0)


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


def test_a_perfect_tool_at_two_tasks_still_wins_nothing() -> None:
    # The honest headline property, and the reason the disjoint fixture had to grow. Two tasks
    # of the widest bracket this harness can produce - one tool passing everything, one failing
    # everything - give 2/2 = [0.3423802275, 1] against 0/2 = [0, 0.6576197725], which overlap
    # on [0.34, 0.66]. A perfect score over two tasks is not evidence of a better tool, and
    # M0's invented +/-0.25 band, which declared a winner here, was flattering the run.
    result_set = _result_set(
        *(
            _result(task, tool, trial, outcome)
            for task in ("t1", "t2")
            for tool, outcome in (("ground-truth", Outcome.PASSED), ("null", Outcome.FAILED))
            for trial in (0, 1)
        )
    )

    report = build_report(result_set, summarise(result_set))

    ground_truth, null = summarise(result_set)
    assert _band(ground_truth) == (0.3423802275, 1.0)
    assert _band(null) == (0.0, 0.6576197725)
    (comparison,) = report.comparisons
    assert comparison.verdict.winner is None
    assert comparison.verdict.reason is VerdictReason.INTERVALS_OVERLAP


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


def test_the_bootstrap_band_on_a_constant_score_is_that_score_twice() -> None:
    # Every one of null's five tasks has a pass rate of 0.0 and every one of ground-truth's has
    # 1.0, so whichever tasks a resample draws, its mean is the sample's mean. A band around a
    # score nothing varies is that score, and a bootstrap that widened it here would be
    # manufacturing spread out of a resampling loop.
    null, ground_truth = summarise(read_result_set(FIXTURES / "results_disjoint.json"))

    assert _pass_at_1_band(null) == (0.0, 0.0)
    assert _pass_at_1_band(ground_truth) == (1.0, 1.0)


def test_the_bootstrap_band_endpoints_are_means_the_tasks_could_have_produced() -> None:
    # alpha's four per-task rates are 1, 1, 1 and 0.5, so a resample of four tasks drawn with
    # replacement has mean (4 - 0.5k)/4, where k is how many times it drew the half-passed task
    # and k ~ Binomial(4, 1/4). The only means that exist are 1, 0.875, 0.75, 0.625 and 0.5.
    #
    # Which two of them the 95% band reads off is arithmetic on that distribution. The top:
    # P(mean = 1) = (3/4)^4 = 81/256 = 0.316, far above the 0.025 tail, so the upper endpoint is
    # 1.0. The bottom: P(mean <= 0.5) = (1/4)^4 = 0.004 < 0.025, while P(mean <= 0.625)
    # = P(k >= 3) = (4 * 3 + 1)/256 = 0.051 > 0.025, so the 2.5th percentile lands on 0.625.
    alpha, _beta = summarise(read_result_set(FIXTURES / "results_overlapping.json"))

    assert alpha.pass_at_1 == 0.875
    assert _pass_at_1_band(alpha) == (0.625, 1.0)


def test_the_bootstrap_band_is_the_same_every_time_the_same_results_are_summarised() -> None:
    # The seed is a constant in the report layer, not a flag and not a clock (ADR-0043). Two
    # runs over one file that printed two different bands would let a reader take whichever
    # band flattered the tool, which is the failure this harness exists to refuse.
    result_set = read_result_set(FIXTURES / "results_overlapping.json")

    first = summarise(result_set)
    second = summarise(result_set)

    assert [_pass_at_1_band(s) for s in first] == [_pass_at_1_band(s) for s in second]


def test_a_significant_paired_p_still_names_no_winner() -> None:
    # The decision this milestone is most at risk of getting wrong (ADR-0044). Ten tasks, one
    # trial each: alpha solves t1..t8, beta solves t1 and t2, and beta's tasks are a subset of
    # alpha's. So the tools disagree about six tasks, all in alpha's favour, and the exact
    # McNemar p is 2 * C(6,0)/2^6 = 2/64 = 0.03125 - significant at any conventional level.
    #
    # The Wilson bands over ten tasks overlap anyway. 8/10: centre = 9.9207294103/13.8414588207
    # = 0.7167, half = (1.959963984540054/13.8414588207) * sqrt(8*2/10 + 0.9603647052)
    # = 0.1416009 * 1.6001139 = 0.2266, so [0.490, 0.943]. 2/10: centre = 3.9207294103/
    # 13.8414588207 = 0.2833, same half, so [0.057, 0.510]. They share [0.490, 0.510].
    #
    # A p of 0.031 says the two tools differ. It does not say which is better by enough to
    # publish, and the verdict is the pass^n intervals' decision alone.
    tasks = tuple(f"t{index}" for index in range(1, 11))
    result_set = _one_trial_each(tasks, {"alpha": set(tasks[:8]), "beta": {"t1", "t2"}})

    report = build_report(result_set, summarise(result_set))

    (comparison,) = report.comparisons
    assert comparison.paired.tasks_compared == 10
    assert comparison.paired.only_tool_a == 6
    assert comparison.paired.only_tool_b == 0
    assert comparison.paired.p_value == 0.03125
    assert comparison.verdict.winner is None
    assert comparison.verdict.reason is VerdictReason.INTERVALS_OVERLAP


def test_a_paired_test_reads_only_the_tasks_both_tools_were_given() -> None:
    # McNemar is paired, so a task only one tool ran carries nothing: there is no second
    # measurement to disagree with. Two tools on disjoint task sets have nothing to compare,
    # and the p is 1.0 - the answer for "no evidence they differ", not a suppressed 0.
    result_set = _result_set(
        _result("t1", "alpha", 0, Outcome.PASSED),
        _result("t2", "alpha", 0, Outcome.PASSED),
        _result("t3", "beta", 0, Outcome.FAILED),
        _result("t4", "beta", 0, Outcome.FAILED),
    )

    report = build_report(result_set, summarise(result_set))

    (comparison,) = report.comparisons
    assert comparison.paired.tasks_compared == 0
    assert comparison.paired.only_tool_a == 0
    assert comparison.paired.only_tool_b == 0
    assert comparison.paired.p_value == 1.0


def test_discordance_is_counted_on_pass_caret_n_not_on_pass_at_1() -> None:
    # t1 is where the two metrics disagree: alpha passes one of its two trials and beta neither.
    # On pass@1 alpha is ahead there; on pass^n neither tool solved it, so the task is
    # concordant and the paired test must not read it. Only t2, which alpha solved outright,
    # counts - one discordant task, not two.
    result_set = _result_set(
        _result("t1", "alpha", 0, Outcome.PASSED),
        _result("t1", "alpha", 1, Outcome.FAILED),
        _result("t1", "beta", 0, Outcome.FAILED),
        _result("t1", "beta", 1, Outcome.FAILED),
        _result("t2", "alpha", 0, Outcome.PASSED),
        _result("t2", "alpha", 1, Outcome.PASSED),
        _result("t2", "beta", 0, Outcome.FAILED),
        _result("t2", "beta", 1, Outcome.FAILED),
    )

    report = build_report(result_set, summarise(result_set))

    (comparison,) = report.comparisons
    assert comparison.paired.tasks_compared == 2
    assert comparison.paired.only_tool_a == 1
    assert comparison.paired.only_tool_b == 0
    # One discordant task: 2 * C(1,0)/2^1 = 1.0. One task in one tool's favour is no evidence.
    assert comparison.paired.p_value == 1.0


def test_two_tools_that_solved_the_same_tasks_have_nothing_to_test() -> None:
    # Every task concordant, so the test is handed no discordant pairs at all and returns 1.0.
    # The tools may still differ; this run did not measure it.
    tasks = ("t1", "t2", "t3")
    result_set = _one_trial_each(tasks, {"alpha": {"t1", "t2"}, "beta": {"t1", "t2"}})

    report = build_report(result_set, summarise(result_set))

    (comparison,) = report.comparisons
    assert comparison.paired.tasks_compared == 3
    assert comparison.paired.only_tool_a == 0
    assert comparison.paired.only_tool_b == 0
    assert comparison.paired.p_value == 1.0


# Invented rates, and deliberately unlike anybody's: no price that could be mistaken for a
# figure this repository maintains is written into a file here (ADR-0046). A hundred dollars
# per million input tokens and two hundred per million output tokens divide by hand.
INPUT_USD_PER_MTOK = Decimal("100.000000")
OUTPUT_USD_PER_MTOK = Decimal("200.000000")
PRICES_SOURCE = "an invented rate card, priced against nothing"


def _prices(*tools: str) -> PriceTable:
    """A table pricing each named tool at the two invented rates above."""
    return PriceTable(
        source=PRICES_SOURCE,
        prices=tuple(
            ToolPrice(
                tool=tool,
                input_usd_per_mtok=INPUT_USD_PER_MTOK,
                output_usd_per_mtok=OUTPUT_USD_PER_MTOK,
            )
            for tool in tools
        ),
    )


def test_without_a_price_every_tool_reports_tokens_and_no_dollars() -> None:
    # The default path, and the only one any report has taken so far. The section is present
    # with a line per tool; what is absent is the money, and the basis says so rather than
    # leaving a blank the reader fills in (ADR-0035, ADR-0046).
    result_set = read_result_set(FIXTURES / "results_disjoint.json")

    report = build_report(result_set, summarise(result_set))

    assert report.prices_source is None
    assert [cost.basis for cost in report.costs] == [CostBasis.NO_PRICE_SUPPLIED] * 2
    assert all(cost.total_usd is None for cost in report.costs)
    assert all(cost.input_usd_per_mtok is None for cost in report.costs)
    # The counts are still reported: what a tool spent in tokens is measured whether or not
    # anybody has priced it.
    _null, ground_truth = report.costs
    assert (ground_truth.input_tokens, ground_truth.output_tokens) == (10240, 960)
    assert ground_truth.solved_tasks == 5


def test_a_priced_tool_reports_a_total_and_a_cost_per_solved_task() -> None:
    # ground-truth spent 10240 input and 960 output tokens over its ten trials. At $100 and
    # $200 per million: (10240 * 100 + 960 * 200) / 1e6 = (1024000 + 192000) / 1e6 = $1.216000.
    # It solved all five tasks - solved meaning pass^n, every trial of the task passing - so
    # 1.216000 / 5 = $0.243200 each.
    result_set = read_result_set(FIXTURES / "results_disjoint.json")

    report = build_report(result_set, summarise(result_set), _prices("ground-truth"))

    _null, ground_truth = report.costs
    assert ground_truth.basis is CostBasis.PRICED
    assert ground_truth.total_usd == Decimal("1.216000")
    assert ground_truth.usd_per_solved_task == Decimal("0.243200")
    assert ground_truth.input_usd_per_mtok == INPUT_USD_PER_MTOK
    assert report.prices_source == PRICES_SOURCE


def test_a_priced_tool_that_recorded_no_tokens_reports_no_spend_rather_than_zero() -> None:
    # The null adapter, priced. It recorded (0, 0), which is genuinely ambiguous between "spent
    # nothing" and "was never instrumented" - every adapter Assay ships hard-codes zero here -
    # so the report declines to print $0.00 for it. The rates stay: a price *was* supplied.
    result_set = read_result_set(FIXTURES / "results_disjoint.json")

    report = build_report(result_set, summarise(result_set), _prices("null"))

    null, _ground_truth = report.costs
    assert null.basis is CostBasis.NO_TOKENS_RECORDED
    assert null.total_usd is None
    assert null.usd_per_solved_task is None
    assert null.output_usd_per_mtok == OUTPUT_USD_PER_MTOK


def test_a_tool_that_burned_tokens_and_solved_nothing_reports_the_total_it_burned() -> None:
    # The branch below "no tokens recorded", and a live case: a tool that spends on a suite it
    # cannot solve. Two trials of 100000 input and 50000 output tokens: (200000 * 100 +
    # 100000 * 200) / 1e6 = (20000000 + 20000000) / 1e6 = $40.000000, over zero solved tasks.
    # The total stays - it is the finding - and only the ratio is suppressed, because dividing
    # by no solved tasks is not an infinite price, it is no measurement.
    result_set = _result_set(
        _result("t1", "spendthrift", 0, Outcome.FAILED, tokens=(100_000, 50_000)),
        _result("t2", "spendthrift", 0, Outcome.FAILED, tokens=(100_000, 50_000)),
    )

    report = build_report(result_set, summarise(result_set), _prices("spendthrift"))

    (cost,) = report.costs
    assert cost.basis is CostBasis.NO_TASKS_SOLVED
    assert cost.solved_tasks == 0
    assert cost.total_usd == Decimal("40.000000")
    assert cost.usd_per_solved_task is None


def test_a_total_that_falls_between_two_millionths_of_a_dollar_rounds_up() -> None:
    # One input token at $0.500000 per million is $0.0000005 - half a microdollar, which the
    # six-place scale money is written at cannot spell. Rounding it down to nothing would
    # report a spend lower than the one incurred, so between the two readings of what a tool
    # cost, Assay takes the larger (ADR-0046).
    result_set = _result_set(_result("t1", "thrifty", 0, Outcome.PASSED, tokens=(1, 0)))
    prices = PriceTable(
        source=PRICES_SOURCE,
        prices=(
            ToolPrice(
                tool="thrifty",
                input_usd_per_mtok=Decimal("0.500000"),
                output_usd_per_mtok=Decimal("0.000000"),
            ),
        ),
    )

    report = build_report(result_set, summarise(result_set), prices)

    (cost,) = report.costs
    assert cost.total_usd == Decimal("0.000001")
    assert cost.usd_per_solved_task == Decimal("0.000001")


def test_a_table_that_prices_one_tool_leaves_the_other_unpriced_rather_than_free() -> None:
    # A partial table is a normal thing to supply, and the tool it misses is reported as
    # unpriced. Reading the absence as free would give the unmeasured tool the best cost per
    # solved task in the report.
    result_set = read_result_set(FIXTURES / "results_overlapping.json")

    report = build_report(result_set, summarise(result_set), _prices("alpha"))

    alpha, beta = report.costs
    assert alpha.basis is CostBasis.PRICED
    assert beta.basis is CostBasis.NO_PRICE_SUPPLIED
    assert beta.total_usd is None


def test_a_price_for_a_tool_the_run_never_measured_prices_nothing() -> None:
    # A rate for a tool that is not in the results is not an error - a reader may price three
    # tools and run two - and it may not conjure a row for a tool nobody measured.
    result_set = read_result_set(FIXTURES / "results_overlapping.json")

    report = build_report(result_set, summarise(result_set), _prices("gamma"))

    assert [cost.tool for cost in report.costs] == ["alpha", "beta"]
    assert all(cost.basis is CostBasis.NO_PRICE_SUPPLIED for cost in report.costs)


def test_an_errored_trials_tokens_stay_in_the_total() -> None:
    # A trial that crashed spent what it spent before it crashed, and money a run cost is money
    # it cost. Excluding those tokens would price the tool that fails most as the cheapest one,
    # which is the denominator ADR-0031 already refuses for the scores.
    result_set = _result_set(
        _result("t1", "flaky", 0, Outcome.PASSED, tokens=(500_000, 0)),
        _result("t1", "flaky", 1, Outcome.ERRORED, tokens=(500_000, 0)),
    )

    report = build_report(result_set, summarise(result_set), _prices("flaky"))

    (cost,) = report.costs
    # 1000000 input tokens at $100 per million is $100.000000; the task is not solved at
    # pass^n, because one of its two trials errored.
    assert cost.input_tokens == 1_000_000
    assert cost.total_usd == Decimal("100.000000")
    assert cost.basis is CostBasis.NO_TASKS_SOLVED


def test_a_price_too_large_to_round_refuses_with_a_sentence_not_a_decimal_signal() -> None:
    # $1e30 per million tokens breaks no rule a rate has, and still multiplies out to a figure
    # no report can round to the microdollar: decimal is asked for more significant digits than
    # its context carries and signals InvalidOperation, whose str() is the bare repr
    # `[<class 'decimal.InvalidOperation'>]`. A price is something somebody supplied, so the
    # refusal is Assay's own and says what was wrong with it (ADR-0048).
    result_set = read_result_set(FIXTURES / "results_disjoint.json")
    prices = PriceTable(
        source=PRICES_SOURCE,
        prices=(
            ToolPrice(
                tool="ground-truth",
                input_usd_per_mtok=Decimal("1E30"),
                output_usd_per_mtok=Decimal("1E30"),
            ),
        ),
    )

    with pytest.raises(CostOutOfRangeError) as excinfo:
        build_report(result_set, summarise(result_set), prices)

    assert "<class" not in str(excinfo.value)
    assert "microdollar" in str(excinfo.value)


def test_a_single_discordant_task_is_one_task_not_one_tasks() -> None:
    # The paired sentence is printed in a report whose subject is precision, and "1 tasks" is
    # a grammatical error in it. Only the first clause names the noun; the second is elliptical
    # and keeps the bare number ADR-0044 fixed for it.
    result_set = _one_trial_each(("t1", "t2"), {"alpha": {"t1"}, "beta": set()})

    report = build_report(result_set, summarise(result_set))

    (comparison,) = report.comparisons
    assert comparison.paired.only_tool_a == 1
    assert format_paired(comparison).startswith("alpha solved 1 task beta did not, and beta ")
