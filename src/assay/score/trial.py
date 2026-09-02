"""One trial end to end: set the workspace up, run the tool, measure what it left behind.

The package's I/O half, the way :mod:`assay.mine.pipeline` is the miner's: the only seams it
touches are the three protocols it is handed - ``History``, ``Adapter``, ``RunnerFactory`` -
so a trial can be exercised on fakes and nothing here knows that git, docker or subprocesses
exist. The sequence is SPEC §3's replayed forward: check the recorded base state out, apply
the task's own test patch so the tests are provably failing, let the adapter work, apply
whatever diff it produced, and run exactly the ids the gate recorded.

The verdict is :func:`assay.score.score_report`'s, with one exception this module owns: an
adapter that reported an error never gets measured at all. ``Outcome.ERRORED`` is the harness
or the tool failing to run, which is not the same finding as the tool producing a wrong
answer, and measuring the wreckage would blur the two - so no diff is applied, no runner is
made, and in M2 that means no container is ever started for the trial.
"""

from pathlib import Path

from assay.adapters import Adapter
from assay.core import AssayError
from assay.mine.models import TestReport
from assay.mine.protocols import History, RunnerFactory
from assay.results import Attempt, Budget, Outcome, Result
from assay.score.executable import score_report
from assay.suite import Task


class TrialSetupError(AssayError):
    """The workspace could not be brought to the state the trial is defined on.

    Raised when the task's own test patch does not apply at its recorded base commit. A
    validated suite guarantees it does - the red->green gate applied this patch to this
    parent and watched it hold - so a refusal here is a broken suite or harness, never the
    tool under evaluation. That is why it is an error rather than an ``Outcome``: scoring
    the tool ``FAILED`` would charge it for a defect it had no part in, and every mis-set-up
    trial would drag its pass rate toward the null adapter's floor unremarked.
    """


def run_trial(
    *,
    task: Task,
    adapter: Adapter,
    budget: Budget,
    history: History,
    runner_for: RunnerFactory,
    timeout_s: int,
) -> Result:
    """Run ``adapter`` against ``task`` once and write the trial down as a :class:`Result`.

    The worktree is destroyed on the way out whatever happens, exactly as in the miner's
    ``run_gate``: cleanup belongs to the seam (``History.worktree`` is a context manager for
    this reason), not to this function.

    Raises:
        TrialSetupError: if the task's test patch does not apply at its base commit.
        pydantic.ValidationError: if the adapter's attempt names a different trial than the
            one this call drove; refusing it here keeps a measurement from being attributed
            to a trial that did not produce it (SPEC §5.5).
    """
    with history.worktree(task.base_commit) as workspace:
        if not history.apply_patch(workspace, task.test_patch):
            raise TrialSetupError(
                f"test patch for task {task.task_id} did not apply "
                f"at its base commit {task.base_commit}"
            )
        attempt = adapter.run(task, workspace, budget)
        if attempt.error is not None:
            return _result(task, adapter, attempt, Outcome.ERRORED)
        report = _measure(
            task=task,
            workspace=workspace,
            diff=attempt.diff,
            history=history,
            runner_for=runner_for,
            timeout_s=timeout_s,
        )
    return _result(task, adapter, attempt, score_report(task, report))


def _measure(
    *,
    task: Task,
    workspace: Path,
    diff: str,
    history: History,
    runner_for: RunnerFactory,
    timeout_s: int,
) -> TestReport | None:
    """The trial's evidence, or ``None`` when there is nothing measurable to score.

    The attempt diff is applied only when it is non-empty. ``git apply`` refuses empty
    input, and ``""`` is the null adapter's whole output - the floor every real result is
    read against (CLAUDE.md) - so the empty diff must reach the tests unapplied and score on
    their evidence, not be turned into a patch failure by a quirk of git's argument
    handling. A non-empty diff that does not apply, and a workspace no runner can be made
    for, both return ``None`` without running anything: :func:`score_report` scores both
    ``FAILED``, and skipping the runner means no container is started for a trial that has
    nothing left to measure.
    """
    if diff and not history.apply_patch(workspace, diff):
        return None
    runner = runner_for(workspace)
    if runner is None:
        return None
    selectors = (*task.fail_to_pass, *task.pass_to_pass)
    return runner.run(workspace, selectors, timeout_s=timeout_s)


def _result(task: Task, adapter: Adapter, attempt: Attempt, outcome: Outcome) -> Result:
    """The trial written down, named by what the harness drove rather than by the attempt.

    ``task_id`` and ``adapter_name`` come from the task this call set up and the adapter it
    called; :class:`Result`'s own validator requires the attempt to agree, so a mislabelled
    attempt is refused loudly here instead of being recorded under whichever trial it
    claimed to be.
    """
    return Result(
        schema_version=1,
        task_id=task.task_id,
        adapter_name=adapter.name,
        trial_index=attempt.trial_index,
        attempt=attempt,
        outcome=outcome,
    )
