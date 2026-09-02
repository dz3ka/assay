"""The proof: the miner run against SPEC §9's fixture reports exactly the expected yield.

Everything else in this suite tests a rule on values. This file runs the real thing - a real
git history, real worktrees, a real uv environment per candidate and real pytest processes -
and asserts the number CLAUDE.md forbids adjusting: 11 commits examined, 7 candidates, 2
accepted, and at least one commit under each of the eight rejection reasons. If the miner's
yield changes, that is a deliberate decision with an ADR behind it, not a test to update.

Two properties are asserted, not one. The totals adding up is the weaker claim - two reasons
swapped would still add up - so every walked fixture commit is also checked against the verdict
its table entry names. ``tests/fixture_repo.py`` is the oracle and derives its numbers from
that table; nothing here imports them from the code under test.

The end-to-end assertions share **one** mining run rather than taking a test each, against the
house style of one property per test: a run is an environment and three pytest processes per
candidate, and paying that three times to assert three views of the same run would buy nothing
but minutes. The per-run budget is a few seconds for the same reason - only ``slow_lookup``'s
red run is slow, and it is slow by an hour.

One rule here is witnessed by stubs instead, and the reason is in the fixture's favour: a test
file that would be read as a command-line option cannot reach the miner from git at all, because
``assay.host.git`` refuses such a path the moment it is reported (``src/assay/host/git.py:414``).
Building a fixture commit around it is impossible, so the walk that must survive one, and the
recorded suite that can genuinely carry one, are driven by a stub history and a stub runner.
"""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import pytest

from assay.host import GitHistory, PytestHostRunner, provision_venv
from assay.mine import (
    CommitRef,
    GateOutcome,
    GateRejection,
    MinedCommit,
    RunnerFactory,
    decide_gate,
    mine_suite,
    pytest_selectors,
    revalidate_suite,
    revalidates,
    split_changes,
    tally_yield,
)

# TestReport and TestStatus are imported under other names on purpose: pytest tries to collect
# any module-level name starting with "Test", and warns about these two on every run if they are
# bound as they are spelled. `TestRunner` is here for the same reason.
from assay.mine import (
    TestReport as Report,
)
from assay.mine import (
    TestRunner as Runner,
)
from assay.mine import (
    TestStatus as Status,
)
from assay.suite import SuiteBody, Task
from tests.fixture_repo import EXPECTED_YIELD, FIXTURE_COMMITS, build_fixture_repo

# The ceiling on one test run. Small on purpose: only `slow_lookup`'s red run is slow, and it
# is slow by an hour, so anything a real run needs is already inside a few seconds.
_RUN_TIMEOUT_S = 10

# A ceiling on a hang rather than a budget: `uv venv` plus an editable install is seconds with
# a warm cache and can be a minute cold, and neither number is a property of the commit.
_PROVISION_TIMEOUT_S = 300

_REPO_SLUG = "widget-fixture"

# pytest's usage error, which is what a root conftest that will not import exits with. Spelled
# here rather than imported from `assay.mine.gate`: this file asserts what the runner actually
# produced, and an oracle that reads its answer out of the code under test proves nothing.
_PYTEST_USAGE_ERROR = 4

_MEAN_OF_EMPTY_TARGET = "tests/test_calc.py::test_mean_of_no_values_is_zero"

# The rest of `tests/test_calc.py`, which passes on both sides of that commit. A task minted
# from it records these as its regression guard, so a hand-built stand-in has to record them
# too: revalidation is reproducing the recorded sets, and a suite that claims no guards where
# the run finds two has not described the same task.
_CALC_PASS_TO_PASS = (
    "tests/test_calc.py::test_mean_divides_by_the_count",
    "tests/test_calc.py::test_total_adds_the_values",
)

# The stub walk's commits. Full-length hex because an accepted candidate writes its parent down
# as a task's `base_commit`, and the suite schema takes 40 characters or nothing; no git object
# is named by any of them.
_STUB_PARENT = "0" * 40
_STUB_UNRUNNABLE = "a" * 40
_STUB_ORDINARY = "b" * 40

# A changed test file no runner can be pointed at, in the one shape `is_test_path` still calls a
# test change: a leading dash makes it an option, and the `_test.py` suffix keeps it in the test
# half of the split, where the interesting failure lives.
_OPTION_SHAPED_TEST = "-x_test.py"

# The recorded shape of the same problem: a suite's `test_files` are taken as written, so a task
# on disk can carry a path git would never have handed the miner.
_RECORDED_OPTION_SHAPED = "-x.py"

# A test file whose only property is being runnable, and the source file beside it.
_ORDINARY_TEST = "tests/test_widget.py"
_ORDINARY_SOURCE = "src/widget.py"
_STUB_TARGET = "tests/test_widget.py::test_widget"


def _runner_for(workspace: Path) -> Runner | None:
    """The host wiring the miner is handed: an environment, then a runner that uses it.

    This is the whole of what ``assay.mine`` does not know. The workspace is a worktree the
    gate has just made, so the environment cannot be provisioned any earlier than here.
    """
    return PytestHostRunner(provision_venv(workspace, timeout_s=_PROVISION_TIMEOUT_S))


def _no_environment(workspace: Path) -> Runner | None:
    """The host wiring for a workspace that cannot be provisioned - what a real repository's
    pre-packaging history looks like once the CLI has caught ``EnvironmentSetupError``.

    A stub rather than a genuinely unprovisionable commit: the only honest real witness would
    be a ``uv pip install`` that fails, which means a network-dependent install in CI.
    """
    return None


def _history(tmp_path: Path) -> GitHistory:
    repo = build_fixture_repo(tmp_path / "build")
    return GitHistory(repo, worktree_root=tmp_path / "worktrees")


def _sha(label: str) -> str:
    return next(commit.sha for commit in FIXTURE_COMMITS if commit.label == label)


def _outcome(rejection: GateRejection | None) -> GateOutcome:
    """A gate verdict with nothing scored - enough for the counting rules to be exercised."""
    targets = () if rejection is not None else ("tests/test_x.py::test_y",)
    return GateOutcome(rejection=rejection, fail_to_pass=targets, pass_to_pass=())


def test_mining_the_fixture_repository_reports_exactly_the_expected_yield(tmp_path: Path) -> None:
    mined: list[MinedCommit] = list(
        mine_suite(
            history=_history(tmp_path),
            runner_for=_runner_for,
            repo_slug=_REPO_SLUG,
            limit=None,
            timeout_s=_RUN_TIMEOUT_S,
        )
    )

    tallied = tally_yield(found.outcome for found in mined)

    assert tallied.commits_examined == EXPECTED_YIELD.commits_examined
    assert tallied.candidates == EXPECTED_YIELD.candidates
    assert tallied.accepted == EXPECTED_YIELD.accepted
    # The full mapping, not a lookup per reason: a reason missing from the report and a reason
    # that fired zero times must not be the same document (ADR-0015).
    assert dict(tallied.rejected) == dict(EXPECTED_YIELD.rejected)
    assert set(tallied.rejected) == set(GateRejection)
    # Every fixture commit reached a verdict: the host wiring provisioned all nine.
    assert tallied.unprovisioned == 0

    # Each reason reached by the commit built to reach it, which is the claim the totals alone
    # would not make.
    assert {
        found.commit.sha: found.outcome.rejection for found in mined if found.outcome is not None
    } == {commit.sha: commit.rejection for commit in FIXTURE_COMMITS if commit.walked}

    # And what an accepted commit hands on: exactly one task, checked out at the parent.
    accepted = [found for found in mined if found.task is not None]
    assert [found.task for found in mined if not _accepted(found)] == [None] * (
        EXPECTED_YIELD.commits_examined - EXPECTED_YIELD.accepted
    )
    for found in accepted:
        task, outcome = found.task, found.outcome
        assert task is not None
        assert outcome is not None
        # SPEC §3 step 2: a task is the repository as it stood *before* the fix.
        assert task.base_commit == found.commit.parent
        assert task.task_id == f"{_REPO_SLUG}-{found.commit.sha[:12]}"
        assert task.fail_to_pass == outcome.fail_to_pass
        assert task.metadata["mined_from_commit"] == found.commit.sha


def test_the_broken_conftest_commit_runs_no_test_at_either_end_of_the_gate(
    tmp_path: Path,
) -> None:
    # The witness for `no_tests_executed`, asserted as evidence before it is asserted as a
    # verdict. The signature is the one ADR-0017 describes and `docs/milestones/m1-yield-
    # httpie.md` measured on a real repository: pytest exit 4, no statuses at all, and an
    # **empty** `uncollectable` - a run that never got as far as a module it could not
    # collect. Reading it as a collect error would be a different claim about a different
    # failure, so the three fields are pinned individually rather than through the verdict.
    #
    # Both ends, not just the red one: the gate may only report "no test ran" when the
    # confirmation run says so too, since a red that ran nothing and a green that ran and
    # failed is an ordinary `still_red`.
    history = _history(tmp_path)
    commit = next(
        found for found in history.commits(limit=None) if found.sha == _sha("broken_conftest_units")
    )
    split = split_changes(history.changed_paths(commit.parent, commit.sha))
    selectors = pytest_selectors(split.test_files)
    test_patch = history.diff(commit.parent, commit.sha, split.test_files)
    ground_truth_patch = history.diff(commit.parent, commit.sha, split.source_files)

    with history.worktree(commit.parent) as workspace:
        assert history.apply_patch(workspace, test_patch)
        runner = _runner_for(workspace)
        assert runner is not None
        red = runner.run(workspace, selectors, timeout_s=_RUN_TIMEOUT_S)
        assert history.apply_patch(workspace, ground_truth_patch)
        green = runner.run(workspace, selectors, timeout_s=_RUN_TIMEOUT_S)

    for report in (red, green):
        assert report.exit_code == _PYTEST_USAGE_ERROR
        assert dict(report.statuses) == {}
        assert report.uncollectable == ()
        assert report.timed_out is False
    # And the verdict that evidence earns: not `still_red`, which would report a fix that did
    # not work when nothing was ever put to the test.
    assert decide_gate(red, [green, green]).rejection is GateRejection.NO_TESTS_EXECUTED


def test_a_task_that_still_goes_red_to_green_revalidates(tmp_path: Path) -> None:
    # `assay validate` on a suite whose one task is known good. Built from git rather than from
    # a mining run, so the revalidation path is exercised on its own: a suite that arrived on
    # disk carries its patches and knows nothing about the commit behind them.
    history = _history(tmp_path)
    suite = SuiteBody(schema_version=1, suite_name="fixture", tasks=(_known_good_task(history),))

    revalidated = list(
        revalidate_suite(
            suite=suite, history=history, runner_for=_runner_for, timeout_s=_RUN_TIMEOUT_S
        )
    )

    [(task, outcome)] = revalidated
    assert task.task_id == suite.tasks[0].task_id
    assert outcome is not None
    assert outcome.fail_to_pass == (_MEAN_OF_EMPTY_TARGET,)
    # The claim `assay validate` makes is this one, not `rejection is None`: the gate accepted
    # *and* it crossed the sets the suite recorded.
    assert revalidates(task, outcome)


def test_a_yield_reports_every_reason_including_the_ones_that_did_not_fire() -> None:
    # A sparse mapping would make "this reason never fired" and "this reason was not looked
    # for" the same document, which is the confusion ADR-0015 exists to end.
    tallied = tally_yield([_outcome(None), _outcome(GateRejection.ALREADY_GREEN)])

    assert set(tallied.rejected) == set(GateRejection)
    assert len(tallied.rejected) == 8
    assert tallied.rejected[GateRejection.ALREADY_GREEN] == 1
    assert tallied.rejected[GateRejection.STILL_RED] == 0


@pytest.mark.parametrize(
    ("rejection", "counts_as_candidate"),
    [
        (None, True),
        (GateRejection.NO_TEST_CHANGES, False),
        (GateRejection.NO_SOURCE_CHANGES, False),
        (GateRejection.PATCH_DID_NOT_APPLY, False),
        (GateRejection.ALREADY_GREEN, True),
        (GateRejection.STILL_RED, True),
        (GateRejection.NO_TESTS_EXECUTED, True),
        (GateRejection.UNSTABLE_GREEN, True),
        (GateRejection.RUN_TIMED_OUT, True),
    ],
    ids=[
        "accepted",
        "no test changes",
        "no source changes",
        "patch did not apply",
        "already green",
        "still red",
        "no tests executed",
        "unstable green",
        "run timed out",
    ],
)
def test_only_a_commit_that_reached_the_gate_counts_as_a_candidate(
    rejection: GateRejection | None, counts_as_candidate: bool
) -> None:
    # The three reasons decided on the diff alone are examined but never run, so counting them
    # as candidates would overstate how much of the history was actually put to the test.
    tallied = tally_yield([_outcome(rejection)])

    assert tallied.commits_examined == 1
    assert tallied.candidates == int(counts_as_candidate)


def test_a_workspace_that_cannot_be_provisioned_does_not_stop_the_walk(tmp_path: Path) -> None:
    # Mining a real repository back past the commit that introduced its packaging is exactly
    # this: every candidate's workspace refuses an environment. The walk has to finish and
    # report a yield anyway - a traceback out of the generator would report nothing at all,
    # which is M1's exit criterion and CLAUDE.md's "every discard is counted" both lost.
    mined: list[MinedCommit] = list(
        mine_suite(
            history=_history(tmp_path),
            runner_for=_no_environment,
            repo_slug=_REPO_SLUG,
            limit=None,
            timeout_s=_RUN_TIMEOUT_S,
        )
    )

    assert len(mined) == EXPECTED_YIELD.commits_examined
    # The three reasons settled before a runner is ever asked for still stand; everything that
    # would have needed an environment has no verdict at all, and no task either.
    assert [found.outcome is None for found in mined].count(True) == 7
    assert all(found.task is None for found in mined)
    assert {found.outcome.rejection for found in mined if found.outcome is not None} == {
        GateRejection.NO_TEST_CHANGES,
        GateRejection.NO_SOURCE_CHANGES,
        GateRejection.PATCH_DID_NOT_APPLY,
    }


def test_a_commit_with_no_environment_is_examined_but_is_not_a_candidate() -> None:
    # Not a rejection reason and not an abort: a third population, counted beside the seven
    # the way ADR-0015 counts merges outside them.
    tallied = tally_yield([None, _outcome(None), _outcome(GateRejection.NO_TEST_CHANGES)])

    assert tallied.commits_examined == 3
    assert tallied.unprovisioned == 1
    assert tallied.candidates == 1
    assert tallied.accepted == 1


def test_the_fixture_yield_is_a_partition_with_nothing_unprovisioned() -> None:
    # SPEC §9's expected yield is a true statement about a repository every commit of which
    # can be provisioned, and stays one now that a third population exists.
    assert EXPECTED_YIELD.unprovisioned == 0
    assert EXPECTED_YIELD.accepted + sum(EXPECTED_YIELD.rejected.values()) == 11


@pytest.mark.parametrize(
    ("outcome", "valid"),
    [
        (GateOutcome(rejection=None, fail_to_pass=("t.py::a",), pass_to_pass=("t.py::b",)), True),
        (GateOutcome(rejection=None, fail_to_pass=("t.py::c",), pass_to_pass=("t.py::b",)), False),
        (GateOutcome(rejection=None, fail_to_pass=("t.py::a",), pass_to_pass=()), False),
        (GateOutcome(rejection=GateRejection.STILL_RED, fail_to_pass=(), pass_to_pass=()), False),
        (None, False),
    ],
    ids=[
        "exact-match",
        "drifted-fail-to-pass",
        "eroded-pass-to-pass",
        "rejected",
        "no-environment",
    ],
)
def test_a_task_revalidates_only_when_it_reproduces_the_sets_it_recorded(
    outcome: GateOutcome | None, valid: bool
) -> None:
    # The gate accepts on whatever crosses red to green now; a suite is a claim about what
    # crossed then. A task whose recorded fail_to_pass has stopped failing at the base state is
    # a task the null adapter passes, and the null adapter brackets every real result at zero.
    assert revalidates(_recorded_task(), outcome) is valid


def test_a_commit_whose_test_half_reads_as_an_option_is_rejected_without_ending_the_walk(
    tmp_path: Path,
) -> None:
    # The runner refuses such a selector loudly, so the whole question is whether it is ever
    # handed one. Decided here instead: the commit is examined, discarded under a reason the
    # yield already counts, and the walk goes on to the next commit.
    runner = _RecordingRunner()
    history = _StubHistory(
        tmp_path,
        {
            _STUB_UNRUNNABLE: (_OPTION_SHAPED_TEST, _ORDINARY_SOURCE),
            _STUB_ORDINARY: (_ORDINARY_TEST, _ORDINARY_SOURCE),
        },
    )

    mined = list(
        mine_suite(
            history=history,
            runner_for=_always(runner),
            repo_slug=_REPO_SLUG,
            limit=None,
            timeout_s=_RUN_TIMEOUT_S,
        )
    )

    rejected, following = mined
    assert rejected.outcome is not None
    assert rejected.outcome.rejection is GateRejection.NO_TEST_CHANGES
    assert rejected.task is None
    # The observable proof that nothing ended: the next commit was not merely yielded, it was
    # put through the gate and became a task.
    assert following.task is not None
    assert runner.calls == [(_ORDINARY_TEST,)] * 3


def test_a_recorded_task_with_no_runnable_test_file_is_one_bad_row_not_a_dead_run(
    tmp_path: Path,
) -> None:
    # `assay validate` walks a suite somebody else wrote, and `Task.test_files` is unconstrained
    # beyond being repo-relative POSIX (ADR-0012), so this is the shape that genuinely arrives.
    # It has to cost one row - reported as failing to revalidate - and not the rest of the run.
    runner = _RecordingRunner()
    suite = SuiteBody(
        schema_version=1,
        suite_name="stub",
        tasks=(
            _stub_task("widget-fixture-000000000001", (_RECORDED_OPTION_SHAPED,)),
            _stub_task("widget-fixture-000000000002", (_ORDINARY_TEST,)),
        ),
    )

    revalidated = list(
        revalidate_suite(
            suite=suite,
            history=_StubHistory(tmp_path, {}),
            runner_for=_always(runner),
            timeout_s=_RUN_TIMEOUT_S,
        )
    )

    [(bad, bad_outcome), (following, following_outcome)] = revalidated
    assert bad_outcome is not None
    assert bad_outcome.rejection is GateRejection.NO_TEST_CHANGES
    assert not revalidates(bad, bad_outcome)
    # And the task after it was still measured, which is the whole difference between a report
    # with one bad row in it and no report at all.
    assert following is suite.tasks[1]
    assert following_outcome is not None
    assert runner.calls == [(_ORDINARY_TEST,)] * 3


def test_the_gate_never_points_a_runner_at_an_empty_selection(tmp_path: Path) -> None:
    # An empty selection is not "run nothing": pytest run with no argument collects the whole
    # repository, so the gate would decide on a suite nobody chose and record the verdict as
    # this task's. The witness is a data file, which is a test change with nothing runnable in
    # it - the same hole an unusable path leaves, reached from the recorded side.
    runner = _RecordingRunner()
    suite = SuiteBody(
        schema_version=1,
        suite_name="stub",
        tasks=(_stub_task("widget-fixture-000000000001", ("tests/data/sample.bin",)),),
    )

    revalidated = list(
        revalidate_suite(
            suite=suite,
            history=_StubHistory(tmp_path, {}),
            runner_for=_always(runner),
            timeout_s=_RUN_TIMEOUT_S,
        )
    )

    assert all(runner.calls), f"the gate ran with an empty selection: {runner.calls}"
    [(_, outcome)] = revalidated
    assert outcome is not None
    assert outcome.rejection is GateRejection.NO_TEST_CHANGES


class _StubHistory:
    """A walk with no git behind it, for the one rule a fixture commit cannot witness.

    ``assay.host.git`` refuses a path that would be read as a command-line option the moment
    git reports it (``src/assay/host/git.py:414``), so no commit can carry such a test file into
    the miner and no fixture repository can be built to prove what happens when one does.

    Every checkout is the same directory and every patch applies: this stub is about the paths
    a commit reports, and the gate's other seams are proved against the real thing above.
    """

    def __init__(self, workspace: Path, changes: dict[str, tuple[str, ...]]) -> None:
        self._workspace = workspace
        self._changes = changes

    def repo_url(self) -> str:
        return "https://example.invalid/widget.git"

    def commits(self, *, limit: int | None) -> Iterator[CommitRef]:
        for sha in self._changes:
            yield CommitRef(sha=sha, parent=_STUB_PARENT, subject=f"commit {sha[:7]}")

    def changed_paths(self, parent: str, commit: str) -> tuple[str, ...]:
        return self._changes[commit]

    def diff(self, parent: str, commit: str, paths: Sequence[str]) -> str:
        return f"--- a/{paths[0]}\n+++ b/{paths[0]}\n"

    def worktree(self, commit: str) -> AbstractContextManager[Path]:
        return nullcontext(self._workspace)

    def apply_patch(self, workspace: Path, patch: str) -> bool:
        return True


class _RecordingRunner:
    """Remembers every selection it was handed, and answers the first run red and the rest green.

    One candidate's worth of answers, which is all any test here asks of it: a red that names a
    failing test and two confirmation runs that agree it passes is the accepting shape, so a
    walk that reaches the gate at all produces a task rather than an incidental rejection.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, workspace: Path, selectors: Sequence[str], *, timeout_s: int) -> Report:
        self.calls.append(tuple(selectors))
        red = len(self.calls) == 1
        return Report(
            statuses={_STUB_TARGET: Status.FAILED if red else Status.PASSED},
            uncollectable=(),
            exit_code=1 if red else 0,
            timed_out=False,
        )


def _always(runner: Runner) -> RunnerFactory:
    """The stub wiring: every workspace gets the same runner, and none is ever unprovisioned."""

    def runner_for(workspace: Path) -> Runner | None:
        return runner

    return runner_for


def _stub_task(task_id: str, test_files: tuple[str, ...]) -> Task:
    """A suite row: the recorded test files matter, and nothing else in it does."""
    return Task(
        schema_version=1,
        task_id=task_id,
        repo_url="https://example.invalid/widget.git",
        base_commit=_STUB_PARENT,
        test_files=test_files,
        test_patch="--- a/x\n+++ b/x\n",
        ground_truth_patch="--- a/y\n+++ b/y\n",
        fail_to_pass=(_STUB_TARGET,),
        pass_to_pass=(),
        prompt="fix it",
        metadata={},
    )


def _recorded_task() -> Task:
    """A task as a suite on disk carries it: two recorded sets and nothing else that matters."""
    return Task(
        schema_version=1,
        task_id="widget-fixture-000000000000",
        repo_url="https://example.invalid/widget.git",
        base_commit="0" * 40,
        test_files=("t.py",),
        test_patch="",
        ground_truth_patch="",
        fail_to_pass=("t.py::a",),
        pass_to_pass=("t.py::b",),
        prompt="fix a",
        metadata={},
    )


def _accepted(found: MinedCommit) -> bool:
    """MinedCommit's invariant, read the way the CLI reads it."""
    return found.outcome is not None and found.outcome.rejection is None


def _known_good_task(history: GitHistory) -> Task:
    """The `mean_of_empty` commit written down as a task, without running the gate first."""
    sha = _sha("mean_of_empty")
    commit = next(found for found in history.commits(limit=None) if found.sha == sha)
    split = split_changes(history.changed_paths(commit.parent, commit.sha))
    return Task(
        schema_version=1,
        task_id=f"{_REPO_SLUG}-{sha[:12]}",
        repo_url=history.repo_url(),
        base_commit=commit.parent,
        test_files=split.test_files,
        test_patch=history.diff(commit.parent, commit.sha, split.test_files),
        ground_truth_patch=history.diff(commit.parent, commit.sha, split.source_files),
        fail_to_pass=(_MEAN_OF_EMPTY_TARGET,),
        pass_to_pass=_CALC_PASS_TO_PASS,
        prompt="mean of no values is zero, not a division by zero",
        metadata={},
    )
