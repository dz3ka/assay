"""One trial end to end, exercised on fakes: setup order, the empty-diff rule, and naming.

:func:`run_trial` is the score package's I/O half, and the only seams it may touch are the
three protocols it is handed - ``History``, ``Adapter``, ``RunnerFactory``. The fakes here
record every call they receive, so the tests can assert not just the verdict but what was and
was not done to reach it: the null adapter's empty diff never reaches ``apply_patch`` (git
apply refuses empty input), and an adapter that already reported an error never costs a
container. No git, no docker, no subprocess appears in this file - that is the property under
test, not a convenience.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

# TestReport, TestRunner and TestStatus are imported under other names on purpose: pytest
# tries to collect any module-level name starting with "Test", and warns about these three on
# every run if they are bound as they are spelled.
from assay.mine import CommitRef
from assay.mine import TestReport as Report
from assay.mine import TestRunner as Runner
from assay.mine import TestStatus as Status
from assay.results import Attempt, Budget, Outcome
from assay.score import TrialSetupError, run_trial
from assay.suite import Task

_TARGET = "tests/test_widget.py::test_target"
_GUARD = "tests/test_widget.py::test_guard"
_TEST_PATCH = "--- a/tests/test_widget.py\n+++ b/tests/test_widget.py\n"
_ATTEMPT_DIFF = "--- a/widget.py\n+++ b/widget.py\n"
_TIMEOUT_S = 300


def _task() -> Task:
    return Task(
        schema_version=1,
        task_id="widget-fixture-000000000000",
        repo_url="https://example.invalid/widget.git",
        base_commit="0" * 40,
        test_files=("tests/test_widget.py",),
        test_patch=_TEST_PATCH,
        ground_truth_patch="--- a/widget.py\n+++ b/widget.py\n",
        fail_to_pass=(_TARGET,),
        pass_to_pass=(_GUARD,),
        prompt="make the target pass",
        metadata={},
    )


def _budget() -> Budget:
    return Budget(
        max_wall_clock_s=600,
        max_input_tokens=None,
        max_output_tokens=None,
        max_tool_calls=None,
        max_usd=None,
    )


def _attempt(*, diff: str, error: str | None = None, task_id: str | None = None) -> Attempt:
    return Attempt(
        schema_version=1,
        adapter_name="scripted",
        adapter_version="0",
        task_id=task_id if task_id is not None else _task().task_id,
        trial_index=3,
        diff=diff,
        input_tokens=0,
        output_tokens=0,
        wall_clock_ms=0,
        tool_calls=0,
        retries=0,
        cost_usd=Decimal("0.000000"),
        error=error,
    )


def _green() -> Report:
    return Report(
        statuses={_TARGET: Status.PASSED, _GUARD: Status.PASSED},
        uncollectable=(),
        exit_code=0,
        timed_out=False,
    )


def _red() -> Report:
    return Report(
        statuses={_TARGET: Status.FAILED, _GUARD: Status.PASSED},
        uncollectable=(),
        exit_code=1,
        timed_out=False,
    )


class _TrialHistory:
    """A ``History`` whose worktree is a plain directory and whose patch outcomes are scripted.

    ``apply_patch`` records every patch it is handed and answers from ``patch_applies`` in call
    order, so a test can assert *which* patches were applied as well as how the answers scored.
    The walking members are never a trial's business, so they fail the test that reaches them.
    """

    def __init__(self, root: Path, *, patch_applies: Sequence[bool] = (True, True)) -> None:
        self.root = root
        self.applied: list[str] = []
        self.checked_out: list[str] = []
        self._answers = list(patch_applies)

    def repo_url(self) -> str:
        return "https://example.invalid/widget.git"

    def commits(self, *, limit: int | None) -> Iterator[CommitRef]:
        raise AssertionError("a trial never walks history")

    def changed_paths(self, parent: str, commit: str) -> tuple[str, ...]:
        raise AssertionError("a trial never diffs commits")

    def diff(self, parent: str, commit: str, paths: Sequence[str]) -> str:
        raise AssertionError("a trial never diffs commits")

    @contextmanager
    def worktree(self, commit: str) -> Iterator[Path]:
        self.checked_out.append(commit)
        yield self.root

    def apply_patch(self, workspace: Path, patch: str) -> bool:
        self.applied.append(patch)
        return self._answers[len(self.applied) - 1]


class _ScriptedAdapter:
    """An ``Adapter`` that answers with a prewritten attempt and records being asked."""

    name = "scripted"
    version = "0"

    def __init__(self, attempt: Attempt) -> None:
        self._attempt = attempt
        self.workspaces: list[Path] = []

    def run(self, task: Task, workspace: Path, budget: Budget) -> Attempt:
        self.workspaces.append(workspace)
        return self._attempt


class _ScriptedRunner:
    """A ``TestRunner`` that records each run it is asked for and answers a fixed report."""

    def __init__(self, report: Report) -> None:
        self._report = report
        self.runs: list[tuple[Path, tuple[str, ...], int]] = []

    def run(self, workspace: Path, selectors: Sequence[str], *, timeout_s: int) -> Report:
        self.runs.append((workspace, tuple(selectors), timeout_s))
        return self._report


class _RecordingFactory:
    """A ``RunnerFactory`` that records every workspace it is asked to equip.

    "No container started" is not observable from a verdict alone; it is observable from this
    list staying empty, which is what the ERRORED and diff-did-not-apply tests assert.
    """

    def __init__(self, runner: Runner | None) -> None:
        self._runner = runner
        self.workspaces: list[Path] = []

    def __call__(self, workspace: Path) -> Runner | None:
        self.workspaces.append(workspace)
        return self._runner


def test_a_trial_whose_diff_turns_the_tests_green_scores_passed(tmp_path: Path) -> None:
    history = _TrialHistory(tmp_path)
    attempt = _attempt(diff=_ATTEMPT_DIFF)

    result = run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(attempt),
        budget=_budget(),
        history=history,
        runner_for=_RecordingFactory(_ScriptedRunner(_green())),
        timeout_s=_TIMEOUT_S,
    )

    assert result.outcome is Outcome.PASSED
    assert result.attempt is attempt
    # The trial is checked out at the task's recorded base state, not at the mined commit.
    assert history.checked_out == [_task().base_commit]


def test_the_result_names_the_trial_the_harness_drove(tmp_path: Path) -> None:
    result = run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(_attempt(diff="")),
        budget=_budget(),
        history=_TrialHistory(tmp_path),
        runner_for=_RecordingFactory(_ScriptedRunner(_red())),
        timeout_s=_TIMEOUT_S,
    )

    assert result.schema_version == 1
    assert result.task_id == _task().task_id
    assert result.adapter_name == "scripted"
    assert result.trial_index == result.attempt.trial_index == 3


def test_the_test_patch_is_applied_before_the_adapter_and_the_attempt_diff_after(
    tmp_path: Path,
) -> None:
    history = _TrialHistory(tmp_path)
    adapter = _ScriptedAdapter(_attempt(diff=_ATTEMPT_DIFF))

    run_trial(
        task=_task(),
        adapter=adapter,
        budget=_budget(),
        history=history,
        runner_for=_RecordingFactory(_ScriptedRunner(_green())),
        timeout_s=_TIMEOUT_S,
    )

    assert history.applied == [_TEST_PATCH, _ATTEMPT_DIFF]
    assert adapter.workspaces == [tmp_path]


def test_the_recorded_sets_are_what_the_runner_is_asked_to_run(tmp_path: Path) -> None:
    runner = _ScriptedRunner(_green())

    run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(_attempt(diff=_ATTEMPT_DIFF)),
        budget=_budget(),
        history=_TrialHistory(tmp_path),
        runner_for=_RecordingFactory(runner),
        timeout_s=_TIMEOUT_S,
    )

    assert runner.runs == [(tmp_path, (_TARGET, _GUARD), _TIMEOUT_S)]


def test_an_empty_attempt_diff_is_never_handed_to_apply_patch(tmp_path: Path) -> None:
    # git apply refuses empty input, and "" is the null adapter's whole output - the floor
    # every real result is read against. The tests must still run, against the workspace with
    # only the test patch applied, and score on their own evidence.
    history = _TrialHistory(tmp_path)
    runner = _ScriptedRunner(_red())

    result = run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(_attempt(diff="")),
        budget=_budget(),
        history=history,
        runner_for=_RecordingFactory(runner),
        timeout_s=_TIMEOUT_S,
    )

    assert history.applied == [_TEST_PATCH]
    assert len(runner.runs) == 1
    assert result.outcome is Outcome.FAILED


def test_an_attempt_diff_that_does_not_apply_scores_failed_without_a_runner(
    tmp_path: Path,
) -> None:
    # The second scripted answer is the attempt diff refusing to apply: there is nothing left
    # to measure, so no runner is made - which in M2 means no container is started.
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    result = run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(_attempt(diff=_ATTEMPT_DIFF)),
        budget=_budget(),
        history=_TrialHistory(tmp_path, patch_applies=(True, False)),
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
    )

    assert result.outcome is Outcome.FAILED
    assert factory.workspaces == []


def test_a_workspace_with_no_runner_scores_failed(tmp_path: Path) -> None:
    result = run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(_attempt(diff=_ATTEMPT_DIFF)),
        budget=_budget(),
        history=_TrialHistory(tmp_path),
        runner_for=_RecordingFactory(None),
        timeout_s=_TIMEOUT_S,
    )

    assert result.outcome is Outcome.FAILED


def test_an_adapter_error_scores_errored_before_any_container_is_started(tmp_path: Path) -> None:
    # An adapter that failed to run is not a tool that produced a wrong answer
    # (``Outcome.ERRORED``'s own docstring), so nothing it left behind is measured: the diff
    # is not applied, no runner is made, no container is started.
    history = _TrialHistory(tmp_path)
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    result = run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(_attempt(diff=_ATTEMPT_DIFF, error="the tool crashed")),
        budget=_budget(),
        history=history,
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
    )

    assert result.outcome is Outcome.ERRORED
    assert factory.workspaces == []
    assert history.applied == [_TEST_PATCH]


def test_a_test_patch_that_does_not_apply_is_a_harness_error_not_a_verdict(
    tmp_path: Path,
) -> None:
    # A validated suite guarantees its test patch applies at its base commit, so a False here
    # is a broken suite or harness. Scoring the tool FAILED would charge it for a defect it
    # had no part in, and the adapter is never run against a workspace that is not the task.
    adapter = _ScriptedAdapter(_attempt(diff=_ATTEMPT_DIFF))
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    with pytest.raises(TrialSetupError):
        run_trial(
            task=_task(),
            adapter=adapter,
            budget=_budget(),
            history=_TrialHistory(tmp_path, patch_applies=(False,)),
            runner_for=factory,
            timeout_s=_TIMEOUT_S,
        )

    assert adapter.workspaces == []
    assert factory.workspaces == []


def test_an_attempt_that_names_another_task_is_refused_rather_than_recorded(
    tmp_path: Path,
) -> None:
    # The result is named by what the harness drove; ``Result``'s own validator refuses an
    # attempt that claims to be someone else's, so a mislabelling adapter fails loudly instead
    # of attributing a measurement to a trial that did not produce it (SPEC §5.5).
    with pytest.raises(ValidationError):
        run_trial(
            task=_task(),
            adapter=_ScriptedAdapter(_attempt(diff="", task_id="some-other-task")),
            budget=_budget(),
            history=_TrialHistory(tmp_path),
            runner_for=_RecordingFactory(_ScriptedRunner(_red())),
            timeout_s=_TIMEOUT_S,
        )
