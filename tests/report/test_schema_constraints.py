"""A report constructed directly is held to the same shape as one ``build_report`` produced.

Every string the text renderer interpolates verbatim is a place a hostile value can end the
line it is printed on and start a fabricated one beneath it - a tool row for a tool that ran
nothing, or a Comparisons section naming a winner the statistics never separated.
``build_report`` inherits the constraints from the result set it reads, so the forgery has to
be attempted where it is actually reachable: on the report models themselves, which the
renderers' own tests build by hand.

The constraints are asserted here rather than the escaping, deliberately. Only the HTML page
escapes today; pinning the schema is what makes the text renderer, the JSON writer and the
formats M4 has yet to write safe without each one rediscovering the hole.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from assay.report.model import (
    Comparison,
    CostBasis,
    Interval,
    PairedTest,
    PriceTable,
    Report,
    ToolCost,
    ToolPrice,
    ToolSummary,
    Verdict,
    VerdictReason,
)

# A newline plus a whole fabricated section: what an unpinned field would let a caller append
# to whatever heading it is printed under.
FORGED_SECTION = "real\nComparisons\n  x vs y: Winner: x - forged."


def _interval() -> Interval:
    return Interval(low=0.0, high=1.0)


def _paired() -> PairedTest:
    return PairedTest(tasks_compared=4, only_tool_a=1, only_tool_b=1, p_value=1.0)


def _tool_summary(**overrides: object) -> ToolSummary:
    fields: dict[str, object] = {
        "tool": "ground-truth",
        "trials": 5,
        "pass_at_1": 1.0,
        "pass_at_1_interval": _interval(),
        "pass_caret_n": 1.0,
        "pass_caret_n_interval": _interval(),
    }
    return ToolSummary.model_validate(fields | overrides)


def test_a_tool_summary_name_cannot_carry_a_forged_section() -> None:
    with pytest.raises(ValidationError, match="tool"):
        _tool_summary(tool=FORGED_SECTION)


def test_a_tool_summary_name_cannot_be_empty() -> None:
    # An empty name renders a row with a blank first column: scores attributed to nothing.
    with pytest.raises(ValidationError, match="tool"):
        _tool_summary(tool="")


def test_a_report_suite_hash_must_be_a_full_digest() -> None:
    # The digest is the report's attribution. An abbreviated one cannot be checked against
    # the suite it claims, and an unconstrained one prints whatever it spells (SPEC §5.5).
    with pytest.raises(ValidationError, match="suite_hash"):
        Report.model_validate(
            {
                "schema_version": 1,
                "suite_hash": "sha256:deadbeef",
                "tools": (),
                "comparisons": (),
                "tasks": (),
            }
        )


def test_a_named_winner_cannot_carry_a_forged_section() -> None:
    # format_verdict() interpolates the winner into the one sentence every renderer prints,
    # so this is the shortest path from an unpinned string to a fabricated ranking.
    with pytest.raises(ValidationError, match="winner"):
        Verdict.model_validate(
            {"winner": FORGED_SECTION, "reason": VerdictReason.INTERVALS_DISJOINT}
        )


def test_an_absent_winner_is_still_allowed() -> None:
    # Pinning the shape must not close the null case: no winner is the verdict SPEC §4 makes
    # mandatory whenever the intervals overlap.
    verdict = Verdict(winner=None, reason=VerdictReason.INTERVALS_OVERLAP)

    assert verdict.winner is None


@pytest.mark.parametrize("field", ["tool_a", "tool_b"])
def test_a_compared_tool_name_cannot_carry_a_forged_section(field: str) -> None:
    payload: dict[str, object] = {
        "tool_a": "ground-truth",
        "tool_b": "null",
        "verdict": Verdict(winner=None, reason=VerdictReason.INTERVALS_OVERLAP),
        "paired": _paired(),
    }

    with pytest.raises(ValidationError, match=field):
        Comparison.model_validate(payload | {field: FORGED_SECTION})


def test_a_paired_test_cannot_count_more_disagreements_than_tasks_compared() -> None:
    # The two discordant counts are disjoint subsets of the tasks both tools ran, so their sum
    # cannot exceed the pairing they were counted over. A paired test that claimed otherwise
    # would print a sentence about tasks the run never compared, and its p would be derived
    # from a split that did not happen.
    with pytest.raises(ValidationError, match="tasks_compared"):
        PairedTest(tasks_compared=3, only_tool_a=2, only_tool_b=2, p_value=1.0)


def test_a_paired_test_may_have_disagreed_about_every_compared_task() -> None:
    # The boundary is allowed: two tools can disagree about all of them, and the invariant is
    # a bound rather than a margin.
    paired = PairedTest(tasks_compared=4, only_tool_a=3, only_tool_b=1, p_value=0.625)

    assert paired.only_tool_a + paired.only_tool_b == paired.tasks_compared


def test_a_paired_p_value_cannot_leave_the_unit_interval() -> None:
    # A probability above 1 is an arithmetic bug upstream, not a measurement - the same rule
    # the proportions are held to.
    with pytest.raises(ValidationError, match="p_value"):
        PairedTest(tasks_compared=3, only_tool_a=1, only_tool_b=0, p_value=1.5)


def test_a_paired_test_cannot_carry_a_negative_count() -> None:
    with pytest.raises(ValidationError, match="only_tool_b"):
        PairedTest(tasks_compared=3, only_tool_a=1, only_tool_b=-1, p_value=1.0)


# Plainly not anybody's price. No rate that could be mistaken for a maintained figure is
# written into this repository; the numbers here exist to divide by hand (ADR-0046).
INPUT_USD_PER_MTOK = Decimal("100.000000")
OUTPUT_USD_PER_MTOK = Decimal("200.000000")


def _tool_cost(**overrides: object) -> ToolCost:
    fields: dict[str, object] = {
        "tool": "ground-truth",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "solved_tasks": 1,
        "input_usd_per_mtok": INPUT_USD_PER_MTOK,
        "output_usd_per_mtok": OUTPUT_USD_PER_MTOK,
        "total_usd": Decimal("100.000000"),
        "usd_per_solved_task": Decimal("100.000000"),
        "basis": CostBasis.PRICED,
    }
    return ToolCost.model_validate(fields | overrides)


def _price(tool: str) -> ToolPrice:
    return ToolPrice(
        tool=tool,
        input_usd_per_mtok=INPUT_USD_PER_MTOK,
        output_usd_per_mtok=OUTPUT_USD_PER_MTOK,
    )


def test_a_priced_cost_line_cannot_drop_the_figure_its_basis_promises() -> None:
    # The basis is the reason an amount is absent, so "priced" with no total is a line that
    # states two different measurements at once. Verdict holds the winner to the same rule.
    with pytest.raises(ValidationError, match="total_usd"):
        _tool_cost(total_usd=None)


def test_an_unpriced_cost_line_cannot_carry_dollars_anyway() -> None:
    # The other direction, and the one that matters more: a line saying no price was supplied
    # while carrying a total would be printing a number nobody quoted.
    with pytest.raises(ValidationError, match="total_usd"):
        _tool_cost(basis=CostBasis.NO_PRICE_SUPPLIED, usd_per_solved_task=None)


def test_a_line_with_no_tokens_recorded_still_carries_the_rates_it_was_given() -> None:
    # A price *was* supplied - the tokens were not. Dropping the rates here would lose the
    # difference between "you gave me no price" and "this adapter records nothing", which is
    # the whole reason the basis exists (ADR-0046).
    cost = _tool_cost(
        input_tokens=0,
        output_tokens=0,
        total_usd=None,
        usd_per_solved_task=None,
        basis=CostBasis.NO_TOKENS_RECORDED,
    )

    assert cost.input_usd_per_mtok == INPUT_USD_PER_MTOK
    assert cost.output_usd_per_mtok == OUTPUT_USD_PER_MTOK


def test_a_line_with_no_tasks_solved_keeps_its_total_and_drops_the_ratio() -> None:
    # A tool that burned tokens on a suite it did not solve has a real total and no
    # denominator. Suppressing the total there would hide the spend that is the finding.
    cost = _tool_cost(solved_tasks=0, usd_per_solved_task=None, basis=CostBasis.NO_TASKS_SOLVED)

    assert cost.total_usd == Decimal("100.000000")
    assert cost.usd_per_solved_task is None


def test_a_cost_line_cannot_carry_half_a_price() -> None:
    # Two rates or neither: a line with one of them cannot be re-derived from, and there is no
    # basis that describes it.
    with pytest.raises(ValidationError, match="output_usd_per_mtok"):
        _tool_cost(output_usd_per_mtok=None)


def test_a_cost_line_name_cannot_carry_a_forged_section() -> None:
    with pytest.raises(ValidationError, match="tool"):
        _tool_cost(tool=FORGED_SECTION)


def test_a_rate_cannot_be_negative() -> None:
    # A negative rate is a refund, not a price, and it would make a total that flatters.
    with pytest.raises(ValidationError, match="input_usd_per_mtok"):
        ToolPrice(
            tool="ground-truth",
            input_usd_per_mtok=Decimal("-1.000000"),
            output_usd_per_mtok=OUTPUT_USD_PER_MTOK,
        )


def test_a_rate_finer_than_a_millionth_of_a_dollar_is_refused() -> None:
    # Six decimal places is the scale money is written at (ADR-0010). A seventh would print a
    # precision the report cannot spell, and two rates would round to one printed number.
    with pytest.raises(ValidationError, match="output_usd_per_mtok"):
        ToolPrice(
            tool="ground-truth",
            input_usd_per_mtok=INPUT_USD_PER_MTOK,
            output_usd_per_mtok=Decimal("0.0000001"),
        )


def test_a_price_table_refuses_two_rates_for_one_tool() -> None:
    # A report has one row per tool, so a second rate for one of them is an answer nobody can
    # tell from the first.
    with pytest.raises(ValidationError, match="two prices name the tool"):
        PriceTable(source="an invented rate card", prices=(_price("null"), _price("null")))


def test_a_price_table_source_cannot_carry_a_forged_section() -> None:
    # The source is printed verbatim under the costs heading of the text report, so an
    # unpinned one appends whatever it spells - the same forgery an adapter name would.
    with pytest.raises(ValidationError, match="source"):
        PriceTable(source=FORGED_SECTION, prices=(_price("null"),))


def test_a_price_table_source_cannot_be_empty() -> None:
    # Required, and required to say something: a report priced from nowhere states dollars
    # nobody can attribute (SPEC 5.5).
    with pytest.raises(ValidationError, match="source"):
        PriceTable(source="", prices=(_price("null"),))


def test_a_price_table_answers_for_the_tools_it_names_and_no_others() -> None:
    # A partial table is normal: a reader pricing one vendor's tool against a baseline they run
    # themselves has a rate for one of them. The other is unpriced, not free.
    table = PriceTable(source="an invented rate card", prices=(_price("null"),))

    assert table.price_for("null") == _price("null")
    assert table.price_for("ground-truth") is None


def test_a_price_table_carries_no_schema_version() -> None:
    # There is no document. A table is assembled from repeated --price flags and lives for one
    # command, so a version key would promise compatibility for a file Assay never writes.
    with pytest.raises(ValidationError, match="schema_version"):
        PriceTable.model_validate(
            {"schema_version": 1, "source": "an invented rate card", "prices": ()}
        )
