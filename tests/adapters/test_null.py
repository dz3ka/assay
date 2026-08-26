"""The null adapter is the floor every real result is read against: it produces nothing.

Pairing it with the ground-truth adapter brackets a run (CLAUDE.md) - one scores everything,
one scores nothing, and a harness that cannot tell those two apart is not measuring anything.
So the diff it returns is asserted to be empty rather than merely falsy, and its accounting is
asserted to be present rather than merely zero.
"""

import json
from decimal import Decimal
from pathlib import Path
from time import monotonic_ns

from assay.adapters import Adapter, NullAdapter
from assay.results import Attempt, Budget, Outcome, Result
from assay.suite import Task

FIXTURES = Path(__file__).parent.parent / "fixtures"

# Proved by ``mypy --strict``, for the reason spelled out in ``test_ground_truth``.
_: Adapter = NullAdapter()


def _task() -> Task:
    document: dict[str, object] = json.loads(
        (FIXTURES / "task_minimal.json").read_text(encoding="utf-8")
    )
    return Task.model_validate(document)


def _budget() -> Budget:
    return Budget(
        max_wall_clock_s=60,
        max_input_tokens=None,
        max_output_tokens=None,
        max_tool_calls=None,
        max_usd=None,
    )


def _run(workspace: Path) -> Attempt:
    return NullAdapter().run(_task(), workspace, _budget())


def test_the_diff_returned_is_empty(tmp_path: Path) -> None:
    attempt = _run(tmp_path)

    assert attempt.diff == ""


def test_the_empty_diff_is_not_reported_as_an_error(tmp_path: Path) -> None:
    # Producing nothing is this adapter's correct behaviour, not a failure to run. An error
    # here would make the floor read as "the harness broke" instead of "the tool solved
    # nothing", and those are different findings (SPEC §4, ``Outcome.ERRORED``).
    attempt = _run(tmp_path)

    assert attempt.error is None


def test_the_attempt_names_the_trial_it_came_from(tmp_path: Path) -> None:
    adapter = NullAdapter()

    attempt = adapter.run(_task(), tmp_path, _budget())

    assert attempt.task_id == _task().task_id
    assert attempt.adapter_name == adapter.name == "null"
    assert attempt.adapter_version == adapter.version
    assert attempt.schema_version == 1


def test_the_attempt_can_be_wrapped_in_a_result_without_contradiction(tmp_path: Path) -> None:
    attempt = _run(tmp_path)

    result = Result(
        schema_version=1,
        task_id=_task().task_id,
        adapter_name="null",
        trial_index=attempt.trial_index,
        attempt=attempt,
        outcome=Outcome.FAILED,
    )

    assert result.attempt is attempt


def test_every_accounting_field_is_populated_and_zero(tmp_path: Path) -> None:
    # SPEC §4.2 again: the floor of a report still has to state what it cost, or a reader
    # cannot tell a free zero from an expensive one.
    attempt = _run(tmp_path)

    assert attempt.input_tokens == 0
    assert attempt.output_tokens == 0
    assert attempt.tool_calls == 0
    assert attempt.retries == 0
    assert attempt.cost_usd == Decimal("0.000000")


def test_the_cost_is_written_to_exactly_six_decimal_places(tmp_path: Path) -> None:
    attempt = _run(tmp_path)

    assert str(attempt.cost_usd) == "0.000000"


def test_the_wall_clock_is_measured_rather_than_declared(tmp_path: Path) -> None:
    before = monotonic_ns()

    attempt = _run(tmp_path)

    elapsed_ms = (monotonic_ns() - before) // 1_000_000
    assert 0 <= attempt.wall_clock_ms <= elapsed_ms


def test_the_workspace_is_not_written_to(tmp_path: Path) -> None:
    _run(tmp_path)

    assert list(tmp_path.iterdir()) == []
