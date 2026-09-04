"""The ground-truth adapter is the oracle that makes the harness's own scoring falsifiable.

It replays a task's known-good diff, so a pipeline that does not score it perfectly has a bug
in it rather than a finding about a tool (SPEC §9). That is only true while the diff it hands
back is the task's own and nothing else - so these tests pin the diff, the accounting that
sits next to it, and the fact that the adapter reaches the workspace not at all.
"""

import json
from decimal import Decimal
from pathlib import Path
from time import monotonic_ns

from assay.adapters import Adapter, GroundTruthAdapter
from assay.results import Attempt, Budget, Outcome, Result
from assay.suite import Task

FIXTURES = Path(__file__).parent.parent / "fixtures"

# Conformance is proved here, statically, by ``mypy --strict``. ``Adapter`` is deliberately
# not ``runtime_checkable``, and an ``isinstance`` check against one that was would only ask
# whether the attribute names exist - never whether ``run`` has the signature SPEC §6 fixed.
_: Adapter = GroundTruthAdapter()


# The trial these tests drive. Deliberately not 0: an adapter that stamped the first trial's
# number whatever it was handed would pass against 0 and only against 0.
_TRIAL_INDEX = 3


def _task() -> Task:
    document: dict[str, object] = json.loads(
        (FIXTURES / "task_minimal.json").read_text(encoding="utf-8")
    )
    return Task.model_validate(document)


def _budget() -> Budget:
    """A ceiling nothing here runs into: an M0 adapter does no work to cap."""
    return Budget(
        max_wall_clock_s=60,
        max_input_tokens=None,
        max_output_tokens=None,
        max_tool_calls=None,
        max_usd=None,
    )


def _run(workspace: Path) -> Attempt:
    return GroundTruthAdapter().run(_task(), workspace, _budget(), trial_index=_TRIAL_INDEX)


def test_the_diff_returned_is_the_tasks_ground_truth_patch(tmp_path: Path) -> None:
    attempt = _run(tmp_path)

    assert attempt.diff == _task().ground_truth_patch
    assert attempt.diff != ""


def test_the_attempt_names_the_trial_it_came_from(tmp_path: Path) -> None:
    # A result set is an attribution claim (SPEC §5.5), so an attempt has to be able to say
    # which task and which tool produced it before a Result will agree to wrap it.
    adapter = GroundTruthAdapter()

    attempt = adapter.run(_task(), tmp_path, _budget(), trial_index=_TRIAL_INDEX)

    assert attempt.task_id == _task().task_id
    assert attempt.adapter_name == adapter.name == "ground-truth"
    assert attempt.adapter_version == adapter.version
    assert attempt.schema_version == 1
    # The trial number is the harness's, not the adapter's: it is recorded exactly as it was
    # handed over, which is what lets n attempts at one task be told apart (ADR-0033).
    assert attempt.trial_index == _TRIAL_INDEX


def test_the_attempt_can_be_wrapped_in_a_result_without_contradiction(tmp_path: Path) -> None:
    attempt = _run(tmp_path)

    result = Result(
        schema_version=1,
        task_id=_task().task_id,
        adapter_name="ground-truth",
        trial_index=_TRIAL_INDEX,
        attempt=attempt,
        outcome=Outcome.PASSED,
    )

    assert result.attempt is attempt


def test_every_accounting_field_is_populated_and_zero(tmp_path: Path) -> None:
    # SPEC §4.2 asks for tokens, wall clock, tool calls, retries and money on every attempt.
    # This adapter calls no model and runs no tool, so the honest figure is zero - written,
    # not omitted, because an absent number and a measured zero must not read the same.
    attempt = _run(tmp_path)

    assert attempt.input_tokens == 0
    assert attempt.output_tokens == 0
    assert attempt.tool_calls == 0
    assert attempt.retries == 0
    assert attempt.cost_usd == Decimal("0.000000")
    assert attempt.error is None


def test_the_cost_is_written_to_exactly_six_decimal_places(tmp_path: Path) -> None:
    # Decimal(0) and Decimal("0.000000") are equal and serialise differently, so equality
    # above does not prove the spelling the schema requires; the exponent does.
    attempt = _run(tmp_path)

    assert str(attempt.cost_usd) == "0.000000"


def test_the_wall_clock_is_measured_rather_than_declared(tmp_path: Path) -> None:
    # A hardcoded latency is a number a report would present as a measurement, so the value
    # has to be bounded by time that actually passed around the call.
    before = monotonic_ns()

    attempt = _run(tmp_path)

    elapsed_ms = (monotonic_ns() - before) // 1_000_000
    assert 0 <= attempt.wall_clock_ms <= elapsed_ms


def test_the_workspace_is_not_written_to(tmp_path: Path) -> None:
    # M0 has no sandbox (SPEC §7), so an adapter that wrote here would be writing on the
    # host. Applying the diff is the runner's job in M2, under a container.
    _run(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_the_attempt_round_trips_through_its_own_schema(tmp_path: Path) -> None:
    attempt = _run(tmp_path)

    assert Attempt.model_validate(attempt.model_dump(mode="json")) == attempt
