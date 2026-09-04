"""The overlap rule: the harness refuses to name a winner it cannot defend (SPEC §4).

Every test here is about a claim the report is allowed to make. Two tools whose pass^n
intervals touch at a single endpoint have not been told apart by the data, so no winner is
named - that refusal is the behaviour KICKOFF item 6 asks for by name, and it lives in one
function so that no renderer can quietly re-derive a ranking of its own.

The rest guards the inputs to that decision: an interval that is not a proportion, or that
runs backwards, would make the comparison meaningless before it is ever taken.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from assay.report import (
    Comparison,
    Interval,
    PairedTest,
    Report,
    TaskLine,
    ToolSummary,
    Verdict,
    VerdictReason,
    build_report,
    decide_verdict,
    format_paired,
    format_verdict,
    overlaps,
)
from assay.results import Attempt, Outcome, Result, ResultSet

SUITE_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


def _summary(tool: str, low: float, high: float) -> ToolSummary:
    """A tool summary that differs from its neighbours only in the interval under test."""
    return ToolSummary(
        tool=tool,
        trials=5,
        pass_at_1=high,
        pass_at_1_interval=Interval(low=high, high=high),
        pass_caret_n=low,
        pass_caret_n_interval=Interval(low=low, high=high),
    )


def _result(task_id: str, adapter_name: str, trial_index: int, outcome: Outcome) -> Result:
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
            wall_clock_ms=1,
            tool_calls=0,
            retries=0,
            cost_usd=Decimal("0.000000"),
            error=None,
        ),
        outcome=outcome,
    )


def test_disjoint_intervals_do_not_overlap_and_name_a_winner() -> None:
    ahead = _summary("ahead", 0.70, 0.90)
    behind = _summary("behind", 0.30, 0.60)

    verdict = decide_verdict(ahead, behind)

    assert not overlaps(ahead.pass_caret_n_interval, behind.pass_caret_n_interval)
    assert verdict.winner == "ahead"
    assert verdict.reason is VerdictReason.INTERVALS_DISJOINT


def test_a_winner_is_named_whichever_argument_it_arrives_as() -> None:
    # The rule is about the measurement, not about call order: swapping the arguments must
    # not swap the finding, or two renderers could print two different leaderboards.
    ahead = _summary("ahead", 0.70, 0.90)
    behind = _summary("behind", 0.30, 0.60)

    assert decide_verdict(behind, ahead).winner == "ahead"
    assert decide_verdict(ahead, behind).winner == "ahead"


def test_overlapping_intervals_declare_no_winner() -> None:
    # SPEC §4: "Tool A 61%, Tool B 58%, not significant" is the honest report. A point
    # estimate that is higher is not a tool that is better.
    a = _summary("a", 0.50, 0.72)
    b = _summary("b", 0.61, 0.83)

    verdict = decide_verdict(a, b)

    assert overlaps(a.pass_caret_n_interval, b.pass_caret_n_interval)
    assert verdict.winner is None
    assert verdict.reason is VerdictReason.INTERVALS_OVERLAP


def test_intervals_that_touch_at_one_endpoint_overlap_so_no_winner_is_declared() -> None:
    # KICKOFF item 6, the exact boundary case: [0.4, 0.6] and [0.6, 0.8] share the single
    # point 0.6. Excluding the endpoint here would let a hair's breadth of separation produce
    # a confident ranking, which is the failure mode the whole rule exists to prevent.
    lower = _summary("lower", 0.4, 0.6)
    upper = _summary("upper", 0.6, 0.8)

    verdict = decide_verdict(lower, upper)

    assert overlaps(lower.pass_caret_n_interval, upper.pass_caret_n_interval)
    assert verdict.winner is None
    assert verdict.reason is VerdictReason.INTERVALS_OVERLAP


def test_a_contained_interval_overlaps_the_one_containing_it() -> None:
    wide = Interval(low=0.1, high=0.9)
    narrow = Interval(low=0.4, high=0.5)

    assert overlaps(wide, narrow)
    assert overlaps(narrow, wide)


def test_an_interval_may_not_run_backwards() -> None:
    with pytest.raises(ValidationError, match="low"):
        Interval(low=0.7, high=0.3)


@pytest.mark.parametrize(("low", "high"), [(-0.1, 0.5), (0.5, 1.1), (1.5, 2.0)])
def test_an_interval_bound_outside_zero_to_one_is_not_a_proportion(low: float, high: float) -> None:
    with pytest.raises(ValidationError):
        Interval(low=low, high=high)


def test_a_degenerate_interval_is_allowed_and_overlaps_itself() -> None:
    # A point interval is what a perfectly certain proportion looks like; refusing it would
    # make the reporter crash on a legitimate measurement.
    point = Interval(low=0.5, high=0.5)

    assert overlaps(point, point)


def test_a_verdict_may_not_name_a_winner_the_intervals_could_not_separate() -> None:
    # The rule is structural, not a convention decide_verdict happens to follow: a Verdict
    # that says "overlap" and names a tool anyway is not a document this schema can spell.
    with pytest.raises(ValidationError, match="winner"):
        Verdict(winner="a", reason=VerdictReason.INTERVALS_OVERLAP)


def test_a_decisive_verdict_must_name_the_tool_that_won() -> None:
    with pytest.raises(ValidationError, match="winner"):
        Verdict(winner=None, reason=VerdictReason.INTERVALS_DISJOINT)


def test_a_verdict_document_may_not_omit_a_field() -> None:
    with pytest.raises(ValidationError, match="reason"):
        Verdict.model_validate({"winner": None})


@pytest.mark.parametrize("reason", list(VerdictReason))
def test_every_verdict_reason_formats_to_stable_prose(reason: VerdictReason) -> None:
    # WP7's three renderers all call this, so the sentence is written once. Prose is
    # deliberately not a field on Verdict: canonical JSON is API, and English is not.
    decisive = reason is VerdictReason.INTERVALS_DISJOINT
    verdict = Verdict(winner="ahead" if decisive else None, reason=reason)

    rendered = format_verdict(verdict)

    assert rendered == format_verdict(verdict)
    assert rendered.strip() == rendered
    assert "None" not in rendered
    assert ("ahead" in rendered) is decisive


def _paired_comparison(paired: PairedTest) -> Comparison:
    """A pairing whose verdict is a refusal, so the paired sentence is what varies."""
    return Comparison(
        tool_a="alpha",
        tool_b="beta",
        verdict=Verdict(winner=None, reason=VerdictReason.INTERVALS_OVERLAP),
        paired=paired,
    )


def test_a_paired_test_over_no_shared_tasks_says_there_was_no_comparison() -> None:
    # Two tools run on different task sets are not a paired experiment at all, and the p of 1.0
    # the test returns for that case would read as "no difference found" if it were printed as
    # a number. It is not a finding; it is the absence of one.
    paired = PairedTest(tasks_compared=0, only_tool_a=0, only_tool_b=0, p_value=1.0)

    assert format_paired(_paired_comparison(paired)) == "no shared tasks; no paired comparison"


def test_a_paired_test_with_nothing_discordant_says_there_was_nothing_to_test() -> None:
    # Every task went the same way for both tools, so McNemar was handed no evidence. Saying so
    # is different from printing p = 1.0000 beside two tools that were never told apart.
    paired = PairedTest(tasks_compared=5, only_tool_a=0, only_tool_b=0, p_value=1.0)

    sentence = format_paired(_paired_comparison(paired))

    assert sentence == "the tools solved the same tasks; nothing to test"


def test_a_paired_sentence_reports_the_p_and_refuses_to_rank_on_it() -> None:
    # The decision ADR-0044 records, in the one place a reader meets it. A significant p beside
    # "No winner" reads as either coyness or a licence unless the sentence says which, and it
    # says: this measures whether they differ, and the pass^n intervals do the ranking.
    paired = PairedTest(tasks_compared=10, only_tool_a=6, only_tool_b=0, p_value=0.03125)

    sentence = format_paired(_paired_comparison(paired))

    assert "alpha solved 6 tasks beta did not" in sentence
    assert "beta solved 0 alpha did not" in sentence
    assert "exact McNemar p = 0.0312" in sentence
    assert "ranking is the pass^n intervals' decision alone." in sentence
    assert "Winner" not in sentence


def test_the_no_winner_sentence_says_why_there_is_none() -> None:
    rendered = format_verdict(Verdict(winner=None, reason=VerdictReason.INTERVALS_OVERLAP))

    assert "no winner" in rendered.lower()
    assert "overlap" in rendered.lower()


def test_a_report_pairs_every_tool_once_and_carries_a_line_per_result() -> None:
    result_set = ResultSet(
        schema_version=1,
        suite_hash=SUITE_HASH,
        results=(
            _result("task-a", "ground-truth", 0, Outcome.PASSED),
            _result("task-a", "null", 0, Outcome.FAILED),
        ),
    )
    summaries = (_summary("ground-truth", 0.9, 1.0), _summary("null", 0.0, 0.1))

    report = build_report(result_set, summaries)

    assert report.suite_hash == SUITE_HASH
    assert report.tools == summaries
    assert report.comparisons == (
        Comparison(
            tool_a="ground-truth",
            tool_b="null",
            verdict=Verdict(winner="ground-truth", reason=VerdictReason.INTERVALS_DISJOINT),
            # One shared task, which ground-truth solved and null did not: 2 * C(1,0)/2 = 1.0.
            paired=PairedTest(tasks_compared=1, only_tool_a=1, only_tool_b=0, p_value=1.0),
        ),
    )
    assert report.tasks == (
        TaskLine(task_id="task-a", repo_path=None, commit_subject=None, outcome=Outcome.PASSED),
        TaskLine(task_id="task-a", repo_path=None, commit_subject=None, outcome=Outcome.FAILED),
    )


def test_a_report_over_one_tool_makes_no_comparisons() -> None:
    result_set = ResultSet(schema_version=1, suite_hash=SUITE_HASH, results=())

    report = build_report(result_set, (_summary("only", 0.4, 0.6),))

    assert report.comparisons == ()
    assert report.tasks == ()


def test_a_repeated_task_adapter_trial_triple_is_reported_as_it_was_recorded() -> None:
    # Duplicates load today on purpose - aggregation semantics land in M4 (SPEC §7), so
    # deduplicating here would silently drop a measurement the store accepted.
    duplicated = _result("task-a", "null", 0, Outcome.ERRORED)
    result_set = ResultSet(
        schema_version=1,
        suite_hash=SUITE_HASH,
        results=(duplicated, duplicated, _result("task-a", "null", 0, Outcome.PASSED)),
    )

    report = build_report(result_set, (_summary("null", 0.0, 0.1),))

    assert len(report.tasks) == 3
    assert [line.outcome for line in report.tasks] == [
        Outcome.ERRORED,
        Outcome.ERRORED,
        Outcome.PASSED,
    ]


def test_task_lines_carry_no_provenance_at_m0() -> None:
    # A ResultSet does not record where a task came from, so the report says so in the
    # schema rather than inventing a path or leaking an unredacted one.
    result_set = ResultSet(
        schema_version=1,
        suite_hash=SUITE_HASH,
        results=(_result("task-a", "null", 0, Outcome.NOT_SCORED),),
    )

    report = build_report(result_set, ())

    assert report.tasks[0].repo_path is None
    assert report.tasks[0].commit_subject is None


def test_a_report_may_not_omit_a_field() -> None:
    with pytest.raises(ValidationError, match="tasks"):
        Report.model_validate({"suite_hash": SUITE_HASH, "tools": (), "comparisons": ()})
