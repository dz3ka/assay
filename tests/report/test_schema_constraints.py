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

import pytest
from pydantic import ValidationError

from assay.report.model import (
    Comparison,
    Interval,
    Report,
    ToolSummary,
    Verdict,
    VerdictReason,
)

# A newline plus a whole fabricated section: what an unpinned field would let a caller append
# to whatever heading it is printed under.
FORGED_SECTION = "real\nComparisons\n  x vs y: Winner: x - forged."


def _interval() -> Interval:
    return Interval(low=0.0, high=1.0)


def _tool_summary(**overrides: object) -> ToolSummary:
    fields: dict[str, object] = {
        "tool": "ground-truth",
        "trials": 5,
        "pass_at_1": 1.0,
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
                "intervals_are_placeholders": True,
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
    }

    with pytest.raises(ValidationError, match=field):
        Comparison.model_validate(payload | {field: FORGED_SECTION})
