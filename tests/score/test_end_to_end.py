"""The bracket: mine the fixture, run both oracles against it, and read the two ends off a report.

Every other test in this suite proves one rule on one seam. This one runs the whole harness -
a real git history, a real host mining pass, a real container image per accepted task, real
pytest processes inside real containers, a suite file and a result file on disk - and asserts
the two numbers CLAUDE.md says must bracket every real result: the ground-truth adapter scores
1.0 and the null adapter scores 0.0. A ground truth below the top means the harness is losing
work a task provably contains; a null above the floor means it is scoring something other than
the tests it claims to run. Either way the numbers it would print about a real tool are
worthless, and no unit test in this package can tell you that.

The assertions go through :func:`assay.report.summarise` rather than through the outcomes,
because the number a reader is handed is the summary, not the trial. ``trials`` is asserted
against ``EXPECTED_YIELD.accepted`` in both directions for the same reason: a perfect score
over an empty task set is also 1.0, and a bracket that can pass vacuously brackets nothing.

Mining runs on the **host** and the trials run in the **sandbox**, which is the split M2 exists
to draw (SPEC §5.2): mining executes code the repository already committed, while a trial
executes whatever a tool left behind. There is no skip path here, for the reason there is none
in ``tests/sandbox`` (see ``tests/sandbox/support.py``).
"""

from pathlib import Path

import pytest

from assay.adapters import Adapter, GroundTruthAdapter, NullAdapter
from assay.host import GitHistory, PytestHostRunner, provision_venv
from assay.mine import TestRunner as Runner
from assay.mine import mine_suite
from assay.report import ToolSummary, summarise
from assay.results import Budget, Outcome, Result, ResultSet, read_result_set, write_result_set
from assay.sandbox import build_task_image, sandbox_runner_for
from assay.score import run_trial
from assay.suite import SuiteBody, Task, load_suite, save_suite
from tests.fixture_repo import EXPECTED_YIELD, build_fixture_repo
from tests.sandbox.support import BUILD_BUDGET_S, TRIAL_LIMITS

_REPO_SLUG = "widget-fixture"

# The ceiling on one *mining* run, and the same few seconds ``tests/mine/test_pipeline.py``
# uses: only `slow_lookup`'s red run is slow, and it is slow by an hour.
_MINE_TIMEOUT_S = 10

# A ceiling on a hang rather than a budget: `uv venv` plus an editable install is seconds warm
# and can be a minute cold, and neither number is a property of the commit being mined.
_PROVISION_TIMEOUT_S = 300

# The ceiling on one trial's test run, which is two container starts over the fixture's own
# small suite. Generous because a wedged daemon should fail here rather than hang the suite.
_TRIAL_TIMEOUT_S = 180

# This run is one trial per task per oracle, so it is trial 0 of the n a real run would drive.
_ONLY_TRIAL = 0

# Neither oracle calls a model, so every cap but the wall clock is deliberately null - "no
# ceiling, and we said so" rather than an absent key (:class:`assay.results.Budget`).
_BUDGET = Budget(
    max_wall_clock_s=_TRIAL_TIMEOUT_S,
    max_input_tokens=None,
    max_output_tokens=None,
    max_tool_calls=None,
    max_usd=None,
)

# What the suite file records as its maker. Not ``assay/<version>``: this one was written by a
# test, and a suite claiming the shipped miner made it would be provenance that is not true.
_GENERATOR = "assay-tests/score-end-to-end"


def _host_runner_for(workspace: Path) -> Runner | None:
    """The host wiring the miner is handed, as ``tests/mine/test_pipeline.py`` builds it.

    Mining is the half of this run that stays on the host: it executes code that is already in
    the repository's history, which is the bargain M1 struck (the CLI's ``HOST_EXECUTION_NOTICE``
    says so out loud). Nothing a tool produced is ever run this side of the wall.
    """
    return PytestHostRunner(provision_venv(workspace, timeout_s=_PROVISION_TIMEOUT_S))


def _mined_tasks(history: GitHistory) -> tuple[Task, ...]:
    """Mine the whole fixture history and return its accepted tasks in suite-file order.

    Sorted by task id because :class:`assay.suite.SuiteBody` accepts no other order and the
    walk's is newest-first - the same sort ``assay mine`` does before it saves.
    """
    mined = mine_suite(
        history=history,
        runner_for=_host_runner_for,
        repo_slug=_REPO_SLUG,
        limit=None,
        timeout_s=_MINE_TIMEOUT_S,
    )
    return tuple(
        sorted(
            (found.task for found in mined if found.task is not None),
            key=lambda task: task.task_id,
        )
    )


def _image_for(history: GitHistory, task: Task) -> str:
    """Build ``task``'s image from a checkout of its base commit, and return the tag.

    Neither the test patch nor any fix is applied first: the image holds the state the tool is
    handed. What a trial runs is the workspace it mounts rather than this tree
    (``tests/sandbox/test_runner.py`` pins that), so an image per base commit is an environment
    per task and not a copy of the answer.
    """
    with history.worktree(task.base_commit) as checkout:
        return build_task_image(
            context=checkout,
            base_commit=task.base_commit,
            exclude_newer=None,
            timeout_s=BUILD_BUDGET_S,
        )


def _trial_results(
    *, tasks: tuple[Task, ...], history: GitHistory, images: dict[str, str], out_root: Path
) -> tuple[Result, ...]:
    """One trial per task per oracle - the smallest run in which both brackets are measured.

    One trial each, not the default five: a trial here is two real container starts, and an
    oracle answers every trial of a task identically, so the four further trials would buy no
    evidence this file does not already have. The numbering they would carry exists now
    (ADR-0033) - each call names its own trial, and repeating this run at ``trial_index=1``
    would record a distinguishable second result rather than a duplicate of the first. The
    n-trial runner that drives that arrives with ``assay run`` in M3.
    """
    adapters: tuple[Adapter, ...] = (GroundTruthAdapter(), NullAdapter())
    return tuple(
        run_trial(
            task=task,
            adapter=adapter,
            budget=_BUDGET,
            history=history,
            runner_for=sandbox_runner_for(
                images[task.task_id], limits=TRIAL_LIMITS, out_root=out_root
            ),
            timeout_s=_TRIAL_TIMEOUT_S,
            trial_index=_ONLY_TRIAL,
        )
        for adapter in adapters
        for task in tasks
    )


@pytest.fixture(scope="module")
def scored(tmp_path_factory: pytest.TempPathFactory) -> ResultSet:
    """The whole run, once: mine, save the suite, build an image per task, score both oracles.

    Module-scoped and shared by both bracket tests, against this suite's usual one-property-per-
    test style and for ``tests/mine/test_pipeline.py``'s reason: the run is a mining pass and
    four containerised trials, and paying for it twice to assert two views of one run would buy
    nothing but minutes.

    The result set is written and read back rather than carried in memory. A run's numbers reach
    a report through a file (:mod:`assay.results.store`), so a measurement that could not
    survive the round trip is one the harness cannot actually report.
    """
    root = tmp_path_factory.mktemp("end-to-end")
    history = GitHistory(build_fixture_repo(root / "repo"), worktree_root=root / "worktrees")

    body = SuiteBody(schema_version=1, suite_name=_REPO_SLUG, tasks=_mined_tasks(history))
    suite_path = root / "suite.json"
    save_suite(suite_path, body, generator=_GENERATOR)
    # Read back, so the tasks scored below are the ones the file holds and the hash the results
    # cite is the digest that addresses them.
    suite = load_suite(suite_path)

    images = {task.task_id: _image_for(history, task) for task in suite.body.tasks}
    out_root = root / "out"
    out_root.mkdir()

    results_path = root / "results.json"
    write_result_set(
        results_path,
        ResultSet(
            schema_version=1,
            suite_hash=suite.suite_hash,
            results=_trial_results(
                tasks=suite.body.tasks, history=history, images=images, out_root=out_root
            ),
        ),
    )
    return read_result_set(results_path)


def _summary(scored: ResultSet, tool: str) -> ToolSummary:
    """The one summary ``tool`` earned, or a failure naming what the report holds instead."""
    summaries = summarise(scored)
    named = [shown.tool for shown in summaries]
    found = [shown for shown in summaries if shown.tool == tool]
    assert len(found) == 1, f"expected one {tool!r} summary, report names {named}"
    return found[0]


def test_the_ground_truth_adapter_scores_the_top_of_the_bracket_on_every_mined_task(
    scored: ResultSet,
) -> None:
    summary = _summary(scored, GroundTruthAdapter.name)

    # Every accepted task was measured: a perfect score over nothing is also 1.0.
    assert summary.trials == EXPECTED_YIELD.accepted
    assert summary.pass_at_1 == 1.0
    assert summary.pass_caret_n == 1.0


def test_the_null_adapter_scores_the_floor_of_the_bracket_on_every_mined_task(
    scored: ResultSet,
) -> None:
    summary = _summary(scored, NullAdapter.name)

    assert summary.trials == EXPECTED_YIELD.accepted
    assert summary.pass_at_1 == 0.0
    assert summary.pass_caret_n == 0.0
    # A zero that is a measured failure rather than a crash. ``ERRORED`` scores zero too and
    # means the opposite thing - the harness broke - so a floor made of errors would read as a
    # working floor while proving the trials never ran (:class:`assay.results.Outcome`).
    floor = [result for result in scored.results if result.adapter_name == NullAdapter.name]
    assert [result.outcome for result in floor] == [Outcome.FAILED] * EXPECTED_YIELD.accepted
