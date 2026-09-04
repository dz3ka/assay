"""One trial end to end, exercised on fakes: setup order, the empty-diff rule, and naming.

:func:`run_trial` is the score package's I/O half, and the only seams it may touch are the
three protocols it is handed - ``History``, ``Adapter``, ``RunnerFactory``. The fakes here
record every call they receive, so the tests can assert not just the verdict but what was and
was not done to reach it: the null adapter's empty diff never reaches ``apply_patch`` (git
apply refuses empty input), and an adapter that already reported an error never costs a
container. No git, no docker, no subprocess appears in this file - that is the property under
test, not a convenience.

The trial number is the harness's (ADR-0033), so the fakes record the ``trial_index`` they
were handed rather than choosing one: an adapter is *told* which of a task's n trials it is
running, and a result that disagrees with what the caller drove is refused rather than
recorded.

Two properties of M3's split are read off the same fakes. The workspace the adapter worked in
is never the workspace that is measured (ADR-0038), so ``_TrialHistory`` hands out a fresh
directory per checkout exactly as a real worktree does, and the tests name which of the two
each seam saw. And a diff that names a test path is refused before it is applied (ADR-0037),
which is observable as the runner factory never being called - the fake asserts the negative,
because "no container was started" cannot be read off a verdict.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

# TestReport, TestRunner and TestStatus are imported under other names on purpose: pytest
# tries to collect any module-level name starting with "Test", and warns about these three on
# every run if they are bound as they are spelled.
from assay.adapters import GroundTruthAdapter
from assay.mine import CommitRef, split_changes
from assay.mine import TestReport as Report
from assay.mine import TestRunner as Runner
from assay.mine import TestStatus as Status
from assay.results import Attempt, Budget, Outcome
from assay.score import TrialSetupError, run_trial
from assay.score.trial import _touches_test_path
from assay.suite import Task

_TARGET = "tests/test_widget.py::test_target"
_GUARD = "tests/test_widget.py::test_guard"
_TEST_PATCH = "--- a/tests/test_widget.py\n+++ b/tests/test_widget.py\n"
_ATTEMPT_DIFF = "--- a/widget.py\n+++ b/widget.py\n"
_TIMEOUT_S = 300

# The task's own test file, rewritten by the tool instead of satisfied: the diff ADR-0037
# exists to refuse, and the one shape that would otherwise mint a confident false PASSED.
_TAMPERED_DIFF = (
    "--- a/tests/test_widget.py\n"
    "+++ b/tests/test_widget.py\n"
    "@@ -1,2 +1,2 @@\n"
    "-    assert widget() == 42\n"
    "+    assert True\n"
)

# A repository's test half as git would report it, mixed with its source half: the data file a
# test needs, a root conftest, and three paths no discovery convention would call a test.
_CHANGED_PATHS = (
    "widget.py",
    "tests/test_widget.py",
    "tests/data/sample.bin",
    "conftest.py",
    "src/widget/core.py",
    "docs/readme.md",
)

# The trial these tests drive. Deliberately not 0: an off-by-one that read the first trial's
# number out of thin air would pass against 0 and only against 0.
_TRIAL_INDEX = 3

# SPEC §4 runs each task n times, default five, and the numbering that produces is 0..n-1.
_TRIALS = 5


def _task(
    *,
    test_files: tuple[str, ...] = ("tests/test_widget.py",),
    ground_truth_patch: str = "--- a/widget.py\n+++ b/widget.py\n",
) -> Task:
    return Task(
        schema_version=1,
        task_id="widget-fixture-000000000000",
        repo_url="https://example.invalid/widget.git",
        base_commit="0" * 40,
        test_files=test_files,
        test_patch=_TEST_PATCH,
        ground_truth_patch=ground_truth_patch,
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


def _attempt(
    *,
    diff: str,
    error: str | None = None,
    task_id: str | None = None,
    trial_index: int = _TRIAL_INDEX,
) -> Attempt:
    return Attempt(
        schema_version=1,
        adapter_name="scripted",
        adapter_version="0",
        task_id=task_id if task_id is not None else _task().task_id,
        trial_index=trial_index,
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

    Each checkout yields its *own* directory, the way ``GitHistory.worktree`` gives every
    checkout a uuid4-named one. A single shared path would make ADR-0038's split invisible to
    every assertion here - the adapter's workspace and the measured workspace would compare
    equal by construction - so the fake models the seam's real behaviour rather than the
    convenient one, and ``worktrees`` records them in the order they were handed out.

    The default answers cover a trial's three patch applications: the test patch of the
    workspace the adapter is given, the test patch of the workspace that is measured, and the
    attempt diff applied into the second of those.
    """

    def __init__(self, root: Path, *, patch_applies: Sequence[bool] = (True, True, True)) -> None:
        self.root = root
        self.applied: list[str] = []
        self.checked_out: list[str] = []
        self.worktrees: list[Path] = []
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
        # Named the way ``GitHistory.worktree`` names its own, so two histories over one root
        # - which is what n trials of a task look like - cannot collide.
        workspace = self.root / f"worktree-{uuid4().hex}"
        workspace.mkdir()
        self.worktrees.append(workspace)
        yield workspace

    def apply_patch(self, workspace: Path, patch: str) -> bool:
        self.applied.append(patch)
        return self._answers[len(self.applied) - 1]


class _ScriptedAdapter:
    """An ``Adapter`` that answers with a prewritten attempt and records being asked.

    It answers with the attempt it was built with whatever trial it is told it is running,
    which is what makes it usable as a *misnumbering* adapter too: hand it an attempt stamped
    0, drive trial 3, and the disagreement has to surface somewhere.
    """

    name = "scripted"
    version = "0"

    def __init__(self, attempt: Attempt) -> None:
        self._attempt = attempt
        self.workspaces: list[Path] = []
        self.trial_indices: list[int] = []

    def run(self, task: Task, workspace: Path, budget: Budget, *, trial_index: int) -> Attempt:
        self.workspaces.append(workspace)
        self.trial_indices.append(trial_index)
        return self._attempt


class _NumberingAdapter:
    """The well-behaved shape: an ``Adapter`` that stamps the trial number it was handed.

    Every real adapter looks like this, because an adapter cannot know which of a task's n
    trials it is unless the harness tells it (ADR-0033).
    """

    name = "scripted"
    version = "0"

    def run(self, task: Task, workspace: Path, budget: Budget, *, trial_index: int) -> Attempt:
        return _attempt(diff=_ATTEMPT_DIFF, trial_index=trial_index)


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
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.PASSED
    assert result.attempt is attempt
    # Both of the trial's workspaces are checked out at the task's recorded base state, not
    # at the mined commit.
    assert history.checked_out == [_task().base_commit, _task().base_commit]


def test_the_result_names_the_trial_the_harness_drove(tmp_path: Path) -> None:
    result = run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(_attempt(diff="")),
        budget=_budget(),
        history=_TrialHistory(tmp_path),
        runner_for=_RecordingFactory(_ScriptedRunner(_red())),
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.schema_version == 1
    assert result.task_id == _task().task_id
    assert result.adapter_name == "scripted"
    # The number comes from this call's argument, not from the attempt: an adapter that
    # numbered itself could otherwise file its result under a trial nobody ran.
    assert result.trial_index == result.attempt.trial_index == _TRIAL_INDEX


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
        trial_index=_TRIAL_INDEX,
    )

    # Two preparations, so the test patch is applied twice - once into the workspace the
    # adapter is handed, once into the workspace that is measured (ADR-0038).
    assert history.applied == [_TEST_PATCH, _TEST_PATCH, _ATTEMPT_DIFF]
    assert adapter.workspaces == [history.worktrees[0]]


def test_the_recorded_sets_are_what_the_runner_is_asked_to_run(tmp_path: Path) -> None:
    history = _TrialHistory(tmp_path)
    runner = _ScriptedRunner(_green())

    run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(_attempt(diff=_ATTEMPT_DIFF)),
        budget=_budget(),
        history=history,
        runner_for=_RecordingFactory(runner),
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert runner.runs == [(history.worktrees[1], (_TARGET, _GUARD), _TIMEOUT_S)]


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
        trial_index=_TRIAL_INDEX,
    )

    assert history.applied == [_TEST_PATCH, _TEST_PATCH]
    assert len(runner.runs) == 1
    assert result.outcome is Outcome.FAILED


def test_an_attempt_diff_that_does_not_apply_scores_failed_without_a_runner(
    tmp_path: Path,
) -> None:
    # The third scripted answer is the attempt diff refusing to apply in the measured
    # workspace: there is nothing left to measure, so no runner is made - which since M2 means
    # no container is started.
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    result = run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(_attempt(diff=_ATTEMPT_DIFF)),
        budget=_budget(),
        history=_TrialHistory(tmp_path, patch_applies=(True, True, False)),
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
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
        trial_index=_TRIAL_INDEX,
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
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.ERRORED
    assert factory.workspaces == []
    # One preparation, not two: the second workspace exists to be measured, and an errored
    # attempt is never measured, so it is never checked out (ADR-0038).
    assert history.applied == [_TEST_PATCH]
    assert len(history.worktrees) == 1


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
            trial_index=_TRIAL_INDEX,
        )

    assert adapter.workspaces == []
    assert factory.workspaces == []


def test_the_adapter_is_told_which_trial_of_the_task_it_is_running(tmp_path: Path) -> None:
    # An adapter cannot know its own trial number - nothing it is handed carries one - so the
    # harness passes it (ADR-0033). A tool that samples differently per trial, or writes a log
    # per attempt, needs the number the report will file its result under.
    adapter = _ScriptedAdapter(_attempt(diff=_ATTEMPT_DIFF))

    run_trial(
        task=_task(),
        adapter=adapter,
        budget=_budget(),
        history=_TrialHistory(tmp_path),
        runner_for=_RecordingFactory(_ScriptedRunner(_green())),
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert adapter.trial_indices == [_TRIAL_INDEX]


def test_an_attempt_that_names_another_trial_is_refused_rather_than_recorded(
    tmp_path: Path,
) -> None:
    # The adapter here is the M0 shape: it hard-codes trial 0 because it has no way of knowing
    # better. Driven as trial 3, that attempt belongs to a trial this call did not run, and
    # ``Result``'s own validator is what refuses to record it under the number the harness
    # drove. Copying the number out of the attempt instead would have made that clause
    # unreachable and recorded the mislabelling silently.
    with pytest.raises(ValidationError):
        run_trial(
            task=_task(),
            adapter=_ScriptedAdapter(_attempt(diff="", trial_index=0)),
            budget=_budget(),
            history=_TrialHistory(tmp_path),
            runner_for=_RecordingFactory(_ScriptedRunner(_red())),
            timeout_s=_TIMEOUT_S,
            trial_index=_TRIAL_INDEX,
        )


def test_n_trials_of_one_task_are_numbered_zero_upwards(tmp_path: Path) -> None:
    # SPEC §4's n trials per task per tool, at the default n=5: five results of one task, each
    # naming its own trial, and no two of them claiming to be the same one. Before the harness
    # owned the number this run was not expressible at all - five attempts stamped 0 are five
    # results that cannot be told apart.
    results = tuple(
        run_trial(
            task=_task(),
            adapter=_NumberingAdapter(),
            budget=_budget(),
            history=_TrialHistory(tmp_path),
            runner_for=_RecordingFactory(_ScriptedRunner(_green())),
            timeout_s=_TIMEOUT_S,
            trial_index=trial_index,
        )
        for trial_index in range(_TRIALS)
    )

    assert tuple(result.trial_index for result in results) == (0, 1, 2, 3, 4)
    assert tuple(result.attempt.trial_index for result in results) == (0, 1, 2, 3, 4)


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
            trial_index=_TRIAL_INDEX,
        )


def test_the_workspace_the_adapter_worked_in_is_not_the_workspace_that_is_measured(
    tmp_path: Path,
) -> None:
    # ADR-0038: the tool gets its own checkout of the base state and the measurement gets a
    # fresh one, so nothing the tool left behind other than its recorded diff can reach the
    # run that scores it. Both trees are base plus the task's own test patch, which is what
    # makes a diff harvested from the first apply cleanly in the second.
    history = _TrialHistory(tmp_path)
    adapter = _ScriptedAdapter(_attempt(diff=_ATTEMPT_DIFF))
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    result = run_trial(
        task=_task(),
        adapter=adapter,
        budget=_budget(),
        history=history,
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.PASSED
    assert history.checked_out == [_task().base_commit, _task().base_commit]
    assert adapter.workspaces == [history.worktrees[0]]
    assert factory.workspaces == [history.worktrees[1]]
    assert adapter.workspaces[0] != factory.workspaces[0]


def test_a_measured_workspace_whose_test_patch_is_refused_is_a_harness_error(
    tmp_path: Path,
) -> None:
    # The second preparation is the same preparation, and its refusal means the same thing:
    # the workspace could not be brought to the state the trial is defined on. Scoring the
    # tool on a tree that is not base plus the test patch would measure something other than
    # the task, so it is an error here exactly as it is before the adapter runs.
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    with pytest.raises(TrialSetupError):
        run_trial(
            task=_task(),
            adapter=_ScriptedAdapter(_attempt(diff=_ATTEMPT_DIFF)),
            budget=_budget(),
            history=_TrialHistory(tmp_path, patch_applies=(True, False)),
            runner_for=factory,
            timeout_s=_TIMEOUT_S,
            trial_index=_TRIAL_INDEX,
        )

    assert factory.workspaces == []


def test_a_diff_that_rewrites_the_failing_test_scores_failed_without_a_runner(
    tmp_path: Path,
) -> None:
    # ADR-0037's whole point. M3 is the first milestone whose diffs are model-authored, and a
    # tool that edits the failing test into a pass would otherwise be measured on a suite it
    # wrote itself: a confident PASSED that means nothing. The diff is refused before it is
    # applied, so no runner is made and no container is started - and the edit stays in the
    # recorded attempt, where a human reading the artefact can see what the tool did.
    history = _TrialHistory(tmp_path)
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    result = run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(_attempt(diff=_TAMPERED_DIFF)),
        budget=_budget(),
        history=history,
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.FAILED
    assert factory.workspaces == []
    assert history.applied == [_TEST_PATCH, _TEST_PATCH]
    assert result.attempt.diff == _TAMPERED_DIFF


@pytest.mark.parametrize(
    "diff",
    [
        "--- a/tests/test_other.py\n+++ b/tests/test_other.py\n",
        "--- /dev/null\n+++ b/conftest.py\n",
        "--- /dev/null\n+++ b/tests/pytest.ini\n",
        (
            "diff --git a/widget.py b/tests/test_widget_moved.py\n"
            "similarity index 100%\n"
            "rename from widget.py\n"
            "rename to tests/test_widget_moved.py\n"
        ),
        (
            "--- a/widget.py\n+++ b/widget.py\n"
            "--- a/tests/test_widget.py\n+++ b/tests/test_widget.py\n"
        ),
    ],
    ids=[
        "another-test-file",
        "a-new-root-conftest",
        "config-under-a-test-directory",
        "a-rename-into-a-test-directory",
        "a-source-change-with-a-test-change-hidden-behind-it",
    ],
)
def test_a_diff_touching_any_test_path_is_refused_not_only_the_declared_ones(
    tmp_path: Path, diff: str
) -> None:
    # The task's ``test_files`` names one file; the rule is wider on purpose (ADR-0037). A new
    # root conftest, a pytest config under ``tests/``, an edit to a different test file and a
    # rename that turns source into a test are each a way to change what the recorded ids mean
    # without touching the declared list - and the last case is the reason the whole diff is
    # read rather than its first header.
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    result = run_trial(
        task=_task(),
        adapter=_ScriptedAdapter(_attempt(diff=diff)),
        budget=_budget(),
        history=_TrialHistory(tmp_path),
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.FAILED
    assert factory.workspaces == []


def test_a_diff_touching_a_declared_test_file_no_convention_would_find_is_refused(
    tmp_path: Path,
) -> None:
    # The other half of the union. A repository whose tests live in ``checks/`` satisfies no
    # discovery convention, but the task itself recorded what its test half was, and a tool
    # editing that file is doing the same thing for the same reason.
    declared = "checks/widget_checks.py"
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    result = run_trial(
        task=_task(test_files=("tests/test_widget.py", declared)),
        adapter=_ScriptedAdapter(_attempt(diff=f"--- a/{declared}\n+++ b/{declared}\n")),
        budget=_budget(),
        history=_TrialHistory(tmp_path),
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.FAILED
    assert factory.workspaces == []


def test_a_ground_truth_diff_satisfies_the_test_path_guard_by_construction(
    tmp_path: Path,
) -> None:
    # The claim ADR-0037 rests on, checked rather than asserted: ``split_changes`` puts every
    # test path in the test half, so the ground-truth half a mined task records cannot name
    # one, and the oracle that must score 1.0 is never refused. The end-to-end bracket
    # (tests/score/test_end_to_end.py) is where this is measured against real git and a real
    # container; here it is proved on the split itself, without either.
    split = split_changes(_CHANGED_PATHS)
    assert split.source_files == ("widget.py", "src/widget/core.py", "docs/readme.md")

    ground_truth = "".join(f"--- a/{path}\n+++ b/{path}\n" for path in split.source_files)
    history = _TrialHistory(tmp_path)
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    result = run_trial(
        task=_task(ground_truth_patch=ground_truth),
        adapter=GroundTruthAdapter(),
        budget=_budget(),
        history=history,
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.PASSED
    assert factory.workspaces == [history.worktrees[1]]
    assert history.applied == [_TEST_PATCH, _TEST_PATCH, ground_truth]


@pytest.mark.parametrize(
    ("diff", "touches"),
    [
        ("", False),
        ("not a diff at all", False),
        ("--- \n+++ \n", False),
        ("--- /dev/null\n+++ b/widget.py\n", False),
        ("--- a/widget.py\n+++ b/widget.py\n+# see tests/test_widget.py for the case\n", False),
        ("--- a/widget.py\n+++ b/widget.py\n+import tests.test_widget\n", False),
        ("--- a/tests/test_widget.py\n", True),
        ("+++ b/tests/test_widget.py\n", True),
        ("--- a/tests/test_widget.py\t2026-09-02 10:00:00 +0000\n", True),
        ("diff --git a/tests/test_widget.py b/tests/test_widget.py\n", True),
        ("copy to tests/test_copy.py\n", True),
    ],
    ids=[
        "empty",
        "prose",
        "headers-naming-nothing",
        "a-new-source-file",
        "a-test-path-in-an-added-comment",
        "a-test-module-imported-by-source",
        "an-old-path-header",
        "a-new-path-header",
        "a-header-with-a-timestamp-field",
        "a-git-header",
        "a-copy-destination",
    ],
)
def test_the_test_path_rule_reads_headers_only_and_answers_every_input(
    diff: str, touches: bool
) -> None:
    # Pure and total: the rule is handed text a model wrote, so it must answer rather than
    # raise, and it must answer on the lines that name paths rather than on the lines that
    # carry content. A test path quoted inside an added line of source is not a test change,
    # and reading it as one would refuse trials for mentioning the file they were asked to fix.
    assert _touches_test_path(diff, _task()) is touches
