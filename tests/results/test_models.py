"""The result schema is an attribution claim: this attempt, on this task, under this suite.

Every rejection below is a document that would otherwise be reported as a measurement - money
spelled two ways so one amount gets two content addresses, a result whose attempt belongs to a
different task, a field this build does not understand. The schema is the project's API
(CLAUDE.md), so what it accepts is what a report may later claim.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from assay.core import JsonValue, canonical_json, content_hash
from assay.results import Attempt, Budget, Outcome, Result, ResultSet

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _minimal_result_set_payload() -> dict[str, JsonValue]:
    """The hand-written fixture, freshly decoded so a test can mutate its copy."""
    payload: dict[str, JsonValue] = json.loads(
        (FIXTURES / "result_set_minimal.json").read_text(encoding="utf-8")
    )
    return payload


def _result_payload() -> dict[str, JsonValue]:
    """The fixture's second result: a scored trial with tokens, latency and money on it."""
    results = _minimal_result_set_payload()["results"]
    assert isinstance(results, list)
    result = results[1]
    assert isinstance(result, dict)
    return result


def _result(**overrides: JsonValue) -> Result:
    return Result.model_validate(_result_payload() | overrides)


def _attempt_payload() -> dict[str, JsonValue]:
    attempt = _result_payload()["attempt"]
    assert isinstance(attempt, dict)
    return attempt


def _attempt(**overrides: JsonValue) -> Attempt:
    return Attempt.model_validate(_attempt_payload() | overrides)


def test_a_hand_written_result_set_round_trips_to_byte_identical_canonical_bytes() -> None:
    """M0's exit criterion (SPEC §7): the file, the model and the hash agree exactly."""
    raw = _minimal_result_set_payload()

    dumped: JsonValue = ResultSet.model_validate(raw).model_dump(mode="json")

    assert canonical_json(dumped) == canonical_json(raw)
    assert content_hash(dumped) == content_hash(raw)


def test_the_fixture_result_set_cites_the_hash_of_the_fixture_suite() -> None:
    # Attribution (SPEC §5.5) is only checkable if the cited digest is a real one, so the
    # fixture pins the suite fixture's actual content address rather than a placeholder.
    suite: dict[str, JsonValue] = json.loads(
        (FIXTURES / "suite_minimal.json").read_text(encoding="utf-8")
    )

    result_set = ResultSet.model_validate(_minimal_result_set_payload())

    assert result_set.suite_hash == content_hash(suite["body"])


def test_a_result_set_document_may_not_omit_a_field() -> None:
    # No field has a default: a default would let a document omit a key and still round-trip
    # to different bytes than it was written with, which is the one thing §7 forbids.
    incomplete = _minimal_result_set_payload()
    del incomplete["suite_hash"]

    with pytest.raises(ValidationError, match="suite_hash"):
        ResultSet.model_validate(incomplete)


def test_an_attempt_document_may_not_omit_a_field() -> None:
    incomplete = _attempt_payload()
    del incomplete["retries"]

    with pytest.raises(ValidationError, match="retries"):
        Attempt.model_validate(incomplete)


def test_an_unknown_field_is_rejected_rather_than_dropped() -> None:
    # SPEC §8.7: a result set written by a future Assay must fail loudly here, because a
    # silently dropped field would re-hash to a different digest and break attribution.
    with pytest.raises(ValidationError, match="cache_hits"):
        _attempt(cache_hits=4)


def test_a_result_cannot_be_mutated_after_validation() -> None:
    result = _result()

    with pytest.raises(ValidationError, match="frozen"):
        result.outcome = Outcome.FAILED


def test_a_result_set_may_contain_no_results() -> None:
    empty = _minimal_result_set_payload() | {"results": []}

    assert ResultSet.model_validate(empty).results == ()


def test_money_is_a_decimal_and_never_a_float() -> None:
    attempt = _attempt()

    assert isinstance(attempt.cost_usd, Decimal)
    assert attempt.cost_usd == Decimal("0.000001")


@pytest.mark.parametrize(
    "cost",
    ["0.000000", "0.000001", "12.345678", "1E-6"],
    ids=["zero", "one-microdollar", "several-dollars", "exponent-notation"],
)
def test_a_cost_written_to_six_places_is_accepted(cost: str) -> None:
    assert _attempt(cost_usd=cost).cost_usd == Decimal(cost)


@pytest.mark.parametrize(
    "cost",
    ["0.1", "1", "0.12345", "0.1234567", "0.0000010"],
    ids=["one-place", "no-places", "five-places", "seven-places", "trailing-zero"],
)
def test_a_cost_not_written_to_six_places_is_rejected_rather_than_rounded(cost: str) -> None:
    # Decimal("1.5") and Decimal("1.500000") are equal and serialise differently, so accepting
    # both would give one amount two content addresses - the ambiguity content addressing
    # exists to remove. Quantising here instead of refusing would re-encode a document to
    # bytes it was not written with.
    with pytest.raises(ValidationError, match="six decimal places"):
        _attempt(cost_usd=cost)


def test_a_float_cost_is_rejected_rather_than_coerced() -> None:
    # A float has no stable canonical encoding, so it must not reach the hash boundary as a
    # Decimal that happens to look reasonable.
    lossy: dict[str, object] = dict(_attempt_payload())
    lossy["cost_usd"] = 0.1

    with pytest.raises(ValidationError, match="six decimal places"):
        Attempt.model_validate(lossy)


def test_a_negative_cost_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cost_usd"):
        _attempt(cost_usd="-0.000001")


@pytest.mark.parametrize(
    "field",
    ["trial_index", "input_tokens", "output_tokens", "wall_clock_ms", "tool_calls", "retries"],
)
def test_a_negative_count_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        _attempt(**{field: -1})


def test_an_attempt_may_record_no_diff_and_an_error() -> None:
    # The null adapter produces no diff, and an adapter that crashed produces a reason.
    attempt = _attempt(diff="", error="adapter exited with status 1")

    assert attempt.diff == ""
    assert attempt.error == "adapter exited with status 1"


def test_the_error_field_must_be_written_even_when_there_is_no_error() -> None:
    incomplete = _attempt_payload()
    del incomplete["error"]

    with pytest.raises(ValidationError, match="error"):
        Attempt.model_validate(incomplete)


def test_outcome_covers_the_four_states_a_trial_can_end_in() -> None:
    assert [outcome.value for outcome in Outcome] == ["passed", "failed", "errored", "not_scored"]


@pytest.mark.parametrize("outcome", list(Outcome), ids=[outcome.value for outcome in Outcome])
def test_an_outcome_round_trips_as_its_own_string(outcome: Outcome) -> None:
    result = _result(outcome=outcome.value)

    dumped: JsonValue = result.model_dump(mode="json")

    assert result.outcome is outcome
    assert isinstance(dumped, dict)
    assert dumped["outcome"] == outcome.value


def test_an_unknown_outcome_is_rejected() -> None:
    with pytest.raises(ValidationError, match="flaky"):
        _result(outcome="flaky")


def test_an_outcome_is_carried_not_computed() -> None:
    # M0 has no scorer (SPEC §7): a passing outcome over an empty diff is the document's
    # claim, and this boundary records it rather than second-guessing it.
    payload = _result_payload()
    attempt = payload["attempt"]
    assert isinstance(attempt, dict)
    attempt["diff"] = ""

    assert Result.model_validate(payload).outcome is Outcome.PASSED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_id", "fixture-repo.0002"),
        ("adapter_name", "some-other-tool"),
        ("trial_index", 4),
    ],
)
def test_a_result_whose_attempt_belongs_elsewhere_is_rejected(field: str, value: JsonValue) -> None:
    # A result names its trial twice: once itself, once in the attempt it carries. Disagreement
    # attributes a measurement to a trial that did not produce it, so it is refused.
    with pytest.raises(ValidationError, match=field):
        _result(**{field: value})


def test_a_budget_must_state_every_cap_including_the_absent_ones() -> None:
    # "Optional" here means the type is X | None, not that the key may be missing: an uncapped
    # budget and a forgotten key must not be the same document.
    with pytest.raises(ValidationError, match="max_usd"):
        Budget.model_validate(
            {
                "max_wall_clock_s": 600,
                "max_input_tokens": None,
                "max_output_tokens": None,
                "max_tool_calls": None,
            }
        )


def test_a_fully_uncapped_budget_still_has_a_wall_clock() -> None:
    budget = Budget(
        max_wall_clock_s=600,
        max_input_tokens=None,
        max_output_tokens=None,
        max_tool_calls=None,
        max_usd=None,
    )

    assert budget.max_wall_clock_s == 600
    assert budget.max_usd is None


def test_a_budget_with_no_wall_clock_at_all_is_rejected() -> None:
    # A trial with a zero-second ceiling can never run; that is a mistake, not a policy.
    with pytest.raises(ValidationError, match="max_wall_clock_s"):
        Budget(
            max_wall_clock_s=0,
            max_input_tokens=None,
            max_output_tokens=None,
            max_tool_calls=None,
            max_usd=None,
        )
