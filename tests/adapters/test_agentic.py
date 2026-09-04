"""The agentic CLI adapter: a tool somebody else wrote, run once, and read off the tree.

Every branch is driven on a fake :class:`assay.adapters.ToolProcess`, which is what the seam is
for: the tool that exits non-zero, the tool killed at its budget and the tool that changed
nothing are all reachable in CI without `claude` being installed, without a container and
without a socket.

Four properties carry more weight than the rest. **The harvest excludes nothing** (ADR-0038):
the diff is `git diff --binary --cached` against a tree recorded before the tool ran, so a tool
that edited a test file has that edit in the record - which is asserted here against *real git*,
over a real worktree, because a fake that returned a canned diff would be asserting the fake.
**A tool killed at its wall clock is measured on what it left**, not errored, the same reading
ADR-0028 gives a cgroup kill. **A step that failed is `Attempt.error` and therefore a trial that
costs no container**, observable as the runner factory never being asked for one. And **nothing
the tool printed reaches the attempt**: an agentic CLI's own output is model text, and the
report is redacted by default precisely so that model text is not what a reader gets by
accident (plan section 7g).
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

# TestReport, TestRunner and TestStatus are imported under other names on purpose: pytest tries
# to collect any module-level name starting with "Test", and warns about these three otherwise.
from assay.adapters import Adapter, AgenticCliAdapter, ProcessOutput, ToolProcess
from assay.host import GitHistory, minimal_env, run_command
from assay.mine import CommitRef
from assay.mine import TestReport as Report
from assay.mine import TestRunner as Runner
from assay.mine import TestStatus as Status
from assay.results import Attempt, Budget, Outcome
from assay.score import run_trial
from assay.suite import Task

_SOURCE_FILE = "widget.py"
_TEST_FILE = "tests/test_widget.py"

_TARGET = f"{_TEST_FILE}::test_target"
_GUARD = f"{_TEST_FILE}::test_guard"

_TEST_PATCH = f"--- a/{_TEST_FILE}\n+++ b/{_TEST_FILE}\n"

_PROMPT = "tests/test_widget.py::test_target fails at this commit. Change the source so it passes."

# The witness's repository, before and after the stub tool has been at it. The tool fixes the
# source *and* weakens the failing assertion, which is the pair ADR-0038 exists to keep visible.
_SOURCE = "def widget():\n    return 41\n"
_FIXED_SOURCE = "def widget():\n    return 42\n"
_TEST_SOURCE = "def test_target():\n    assert True\n\n\ndef test_guard():\n    pass\n"
_WEAKENED_TEST = "def test_target():\n    pass\n"

# The same idea as _TEST_PATCH, but a patch real git will apply: the failing assertion, added to
# the committed test file exactly as a mined task's test patch adds it.
_REAL_TEST_PATCH = (
    f"diff --git a/{_TEST_FILE} b/{_TEST_FILE}\n"
    f"--- a/{_TEST_FILE}\n"
    f"+++ b/{_TEST_FILE}\n"
    "@@ -1,5 +1,5 @@\n"
    " def test_target():\n"
    "-    assert True\n"
    "+    assert widget() == 42\n"
    " \n"
    " \n"
    " def test_guard():\n"
)

# What the tool is; the executable is injected rather than looked up, so these tests name a path
# that exists nowhere and never has to.
_EXECUTABLE = "/usr/local/bin/claude"
_MODEL = "claude-sonnet-4-5"

# The environment the adapter is configured with, passed through to every child verbatim. The
# key-shaped value is not a key and could not authenticate anything; it is here to be searched
# for in everything the adapter produces (plan section 7a).
_API_KEY = "sk-ant-not-a-real-key"
_ENV: Mapping[str, str] = {"PATH": "/usr/bin", "ANTHROPIC_API_KEY": _API_KEY}

# A tree object, as `git write-tree` prints one. Forty hex characters, and the adapter is
# required to refuse anything else rather than interpolate it into the harvest's argv.
_BASELINE = "9" * 40

# What the harvest returns when the tool did something: a diff naming source and no test path.
_HARVESTED = (
    f"diff --git a/{_SOURCE_FILE} b/{_SOURCE_FILE}\n"
    f"--- a/{_SOURCE_FILE}\n+++ b/{_SOURCE_FILE}\n"
    "@@ -1,2 +1,2 @@\n-    return 41\n+    return 42\n"
)

# The trial these tests drive. Deliberately not 0: an adapter that stamped whatever the first
# trial's number happened to be would pass against 0 and only against 0 (ADR-0033).
_TRIAL_INDEX = 3

_MAX_WALL_CLOCK_S = 900
_TIMEOUT_S = 300

# The budget for the real-git witness's own setup commands. Seconds of work; long enough that a
# cold `git` on Windows is not a flake.
_GIT_BUDGET_S = 120


class _ScriptedProcess:
    """A ``ToolProcess`` that answers each call from a script and records every one of them.

    The script is read positionally, so a test states what the fifth call answers by stating
    what the first four did. Running past the end of it is an assertion failure rather than a
    default answer: an adapter that made a sixth call would otherwise be measured against a
    fake that had opinions about calls nobody designed.
    """

    def __init__(self, *answers: ProcessOutput) -> None:
        self._answers = list(answers)
        self.calls: list[tuple[tuple[str, ...], Path, int, Mapping[str, str]]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_s: int,
        env: Mapping[str, str],
    ) -> ProcessOutput:
        self.calls.append((tuple(argv), cwd, timeout_s, dict(env)))
        assert len(self.calls) <= len(self._answers), f"unscripted call: {tuple(argv)!r}"
        return self._answers[len(self.calls) - 1]

    @property
    def argvs(self) -> list[tuple[str, ...]]:
        return [argv for argv, _, _, _ in self.calls]


class _StubTool:
    """Real git for the harvest, and a stub that edits two files where the tool would run.

    The seam is where a tool is bound, so this is the shape the production binding has too:
    the harvest's `git` runs on the host over the worktree, and the tool's own argv is the one
    that goes somewhere else (in production, into a container). What matters for the witness
    below is that every `git` here is really git, answering about a real worktree.
    """

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_s: int,
        env: Mapping[str, str],
    ) -> ProcessOutput:
        if argv[0] == _EXECUTABLE:
            (cwd / _SOURCE_FILE).write_text(_FIXED_SOURCE, encoding="utf-8", newline="\n")
            # The edit ADR-0038 exists to keep visible: the failing assertion, weakened away.
            (cwd / _TEST_FILE).write_text(_WEAKENED_TEST, encoding="utf-8", newline="\n")
            return ProcessOutput(exit_code=0, stdout="", stderr="", timed_out=False)
        result = run_command(argv, cwd=cwd, timeout_s=timeout_s, env=env)
        return ProcessOutput(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=False,
        )


class _TrialHistory:
    """A ``History`` whose worktree is a plain directory and whose patches always apply.

    Each checkout yields its own directory, the way ``GitHistory.worktree`` does, so the
    workspace the adapter worked in and the workspace that is measured stay distinguishable
    (ADR-0038). The walking members are never a trial's business, so they fail the test that
    reaches them.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.applied: list[str] = []
        self.worktrees: list[Path] = []

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
        workspace = self.root / f"worktree-{uuid4().hex}"
        workspace.mkdir()
        self.worktrees.append(workspace)
        yield workspace

    def apply_patch(self, workspace: Path, patch: str) -> bool:
        self.applied.append(patch)
        return True


class _ScriptedRunner:
    """A ``TestRunner`` that answers a fixed report and records each run it is asked for."""

    def __init__(self, report: Report) -> None:
        self._report = report
        self.runs: list[tuple[Path, tuple[str, ...], int]] = []

    def run(self, workspace: Path, selectors: Sequence[str], *, timeout_s: int) -> Report:
        self.runs.append((workspace, tuple(selectors), timeout_s))
        return self._report


class _RecordingFactory:
    """A ``RunnerFactory`` that records every workspace it is asked to equip.

    "No container was started" cannot be read off a verdict; it is this list staying empty.
    """

    def __init__(self, runner: Runner | None) -> None:
        self._runner = runner
        self.workspaces: list[Path] = []

    def __call__(self, workspace: Path) -> Runner | None:
        self.workspaces.append(workspace)
        return self._runner


def _ok(stdout: str = "") -> ProcessOutput:
    return ProcessOutput(exit_code=0, stdout=stdout, stderr="", timed_out=False)


def _failed(stderr: str, *, exit_code: int = 1) -> ProcessOutput:
    return ProcessOutput(exit_code=exit_code, stdout="", stderr=stderr, timed_out=False)


def _killed() -> ProcessOutput:
    return ProcessOutput(exit_code=-1, stdout="", stderr="", timed_out=True)


def _worked(*, harvested: str = _HARVESTED, tool: ProcessOutput | None = None) -> _ScriptedProcess:
    """The five calls one clean run makes: stage, baseline, tool, stage, harvest."""
    return _ScriptedProcess(
        _ok(),
        _ok(f"{_BASELINE}\n"),
        tool if tool is not None else _ok("done"),
        _ok(),
        _ok(harvested),
    )


def _task() -> Task:
    return Task(
        schema_version=1,
        task_id="widget-fixture-000000000000",
        repo_url="https://example.invalid/widget.git",
        base_commit="0" * 40,
        test_files=(_TEST_FILE,),
        test_patch=_TEST_PATCH,
        ground_truth_patch=f"--- a/{_SOURCE_FILE}\n+++ b/{_SOURCE_FILE}\n",
        fail_to_pass=(_TARGET,),
        pass_to_pass=(_GUARD,),
        prompt=_PROMPT,
        metadata={},
    )


def _budget() -> Budget:
    return Budget(
        max_wall_clock_s=_MAX_WALL_CLOCK_S,
        max_input_tokens=None,
        max_output_tokens=None,
        max_tool_calls=None,
        max_usd=None,
    )


def _green() -> Report:
    return Report(
        statuses={_TARGET: Status.PASSED, _GUARD: Status.PASSED},
        uncollectable=(),
        exit_code=0,
        timed_out=False,
    )


def _adapter(process: ToolProcess) -> AgenticCliAdapter:
    return AgenticCliAdapter(process=process, executable=_EXECUTABLE, model=_MODEL, env=dict(_ENV))


def _run(process: _ScriptedProcess, workspace: Path) -> Attempt:
    return _adapter(process).run(_task(), workspace, _budget(), trial_index=_TRIAL_INDEX)


# Conformance is proved here, statically, by ``mypy --strict``; ``Adapter`` is deliberately not
# ``runtime_checkable``, and an ``isinstance`` check would only ask whether the names exist.
_: Adapter = AgenticCliAdapter(
    process=_ScriptedProcess(), executable=_EXECUTABLE, model=_MODEL, env={}
)


def test_the_diff_is_whatever_the_harvest_read_out_of_the_tree(tmp_path: Path) -> None:
    # Verbatim: the tool's work is the tree it left, and the diff is git's account of it.
    assert _run(_worked(), tmp_path).diff == _HARVESTED


def test_the_harvest_stages_everything_and_diffs_against_the_baseline(tmp_path: Path) -> None:
    # ADR-0038's contract, spelled as the five calls it is: stage, record a baseline tree, run
    # the tool, stage again, and diff the two staged states. No pathspec anywhere - an
    # exclusion is what launders a test edit out of the record.
    process = _worked()
    _run(process, tmp_path)

    assert process.argvs[0] == ("git", "add", "-A")
    assert process.argvs[1] == ("git", "write-tree")
    assert process.argvs[3] == ("git", "add", "-A")
    assert process.argvs[4] == ("git", "diff", "--binary", "--cached", _BASELINE)


def test_the_tool_is_run_in_the_workspace_under_the_budgets_wall_clock(tmp_path: Path) -> None:
    process = _worked()
    _run(process, tmp_path)
    argv, cwd, timeout_s, _ = process.calls[2]

    assert argv[0] == _EXECUTABLE
    assert cwd == tmp_path
    assert timeout_s == _MAX_WALL_CLOCK_S


def test_the_tool_is_asked_the_task_and_told_the_test_path_rule(tmp_path: Path) -> None:
    # Told rather than silently refused by it: a harness that scores a tool ``FAILED`` for
    # breaking a rule it never stated is measuring the harness's own reticence (ADR-0037).
    process = _worked()
    _run(process, tmp_path)
    asked = "\n".join(process.calls[2][0])

    assert _PROMPT in asked
    assert "test" in asked.lower()
    assert _MODEL in process.argvs[2]


def test_every_child_gets_exactly_the_environment_the_adapter_was_configured_with(
    tmp_path: Path,
) -> None:
    # Complete and never merged with the ambient one: what a tool under evaluation may see is
    # decided where it is configured, not here (plan section 7a).
    process = _worked()
    _run(process, tmp_path)

    assert [env for _, _, _, env in process.calls] == [dict(_ENV)] * 5


def test_a_tool_that_changed_nothing_records_an_empty_diff_and_no_error(tmp_path: Path) -> None:
    # The null adapter's answer, arrived at honestly: producing nothing is a finding about the
    # tool, and calling it an error would move it out of "the tool failed" and into "the
    # harness broke".
    attempt = _run(_worked(harvested=""), tmp_path)

    assert attempt.diff == ""
    assert attempt.error is None


def test_a_tool_killed_at_its_budget_is_measured_on_what_it_left(tmp_path: Path) -> None:
    # The reading ADR-0028 gives a cgroup kill, applied to a wall clock: a tool that ran out of
    # time produced whatever it had produced by then, and that is a countable outcome rather
    # than an incident. Read before the exit code, which a killed process never chose.
    partial = "--- a/widget.py\n+++ b/widget.py\n"
    attempt = _run(_worked(tool=_killed(), harvested=partial), tmp_path)

    assert attempt.error is None
    assert attempt.diff == partial


def test_a_tool_that_exits_nonzero_errors_the_trial_and_starts_no_container(
    tmp_path: Path,
) -> None:
    process = _ScriptedProcess(_ok(), _ok(f"{_BASELINE}\n"), _failed("boom", exit_code=2))
    factory = _RecordingFactory(_ScriptedRunner(_green()))
    result = run_trial(
        task=_task(),
        adapter=_adapter(process),
        budget=_budget(),
        history=_TrialHistory(tmp_path),
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.ERRORED
    assert result.attempt.error is not None
    assert "2" in result.attempt.error
    assert factory.workspaces == []


def test_the_error_never_quotes_what_the_tool_printed(tmp_path: Path) -> None:
    # An agentic CLI's own output is model text, and an attempt is written into a result set
    # and rendered into a report. Neither the completion nor anything the tool echoed out of
    # its environment goes there (plan section 7a and 7g).
    printed = f"I read the key {_API_KEY} and here is my plan"
    process = _ScriptedProcess(
        _ok(),
        _ok(f"{_BASELINE}\n"),
        ProcessOutput(exit_code=1, stdout=printed, stderr=printed, timed_out=False),
    )
    attempt = _run(process, tmp_path)

    assert attempt.error is not None
    assert _API_KEY not in attempt.model_dump_json()
    assert "plan" not in attempt.model_dump_json()


@pytest.mark.parametrize("step", [0, 1, 3, 4])
def test_a_harvest_step_that_fails_errors_rather_than_records_a_partial_diff(
    tmp_path: Path, step: int
) -> None:
    # Nonzero at any step is the harness failing, not the tool: a diff harvested through a
    # broken step is an account of nothing, and recording it would put a number in a report
    # that no reproduction could reach (ADR-0038).
    answers = [_ok(), _ok(f"{_BASELINE}\n"), _ok("done"), _ok(), _ok(_HARVESTED)]
    answers[step] = _failed("fatal: not a git repository")
    attempt = _run(_ScriptedProcess(*answers[: step + 1]), tmp_path)

    assert attempt.error is not None
    assert attempt.diff == ""


def test_a_baseline_that_is_not_a_tree_object_is_refused_before_it_reaches_an_argv(
    tmp_path: Path,
) -> None:
    # The value goes into the harvest's own command line, so it is checked where it arrives,
    # the posture ``host/git.py``'s ``_checked_revision`` takes towards an object name.
    process = _ScriptedProcess(_ok(), _ok("HEAD --all\n"))
    attempt = _run(process, tmp_path)

    assert attempt.error is not None
    assert len(process.calls) == 2


def test_the_attempt_names_the_tool_the_task_and_the_trial(tmp_path: Path) -> None:
    attempt = _run(_worked(), tmp_path)

    assert attempt.adapter_name == "agentic"
    assert _MODEL in attempt.adapter_version
    assert attempt.task_id == _task().task_id
    assert attempt.trial_index == _TRIAL_INDEX


def test_the_cost_is_a_recorded_zero_written_to_six_decimal_places(tmp_path: Path) -> None:
    # M3 records tokens, not money (SPEC section 7 puts cost accounting in M4).
    assert str(_run(_worked(), tmp_path).cost_usd) == "0.000000"


def test_the_attempt_round_trips_through_its_own_schema(tmp_path: Path) -> None:
    attempt = _run(_worked(), tmp_path)

    assert Attempt.model_validate_json(attempt.model_dump_json()) == attempt


def _real_repo(root: Path) -> tuple[Path, str]:
    """A one-commit git repository holding a source file and a test file, and its head sha."""
    repo = root / "repo"
    (repo / "tests").mkdir(parents=True)
    # LF pinned: _REAL_TEST_PATCH is exact, and a newline translated on the way to disk is a
    # hunk that no longer matches the file it describes.
    (repo / _SOURCE_FILE).write_text(_SOURCE, encoding="utf-8", newline="\n")
    (repo / _TEST_FILE).write_text(_TEST_SOURCE, encoding="utf-8", newline="\n")
    env = minimal_env() | {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b.invalid"}
    env |= {"GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@b.invalid"}
    for argv in (
        ("git", "init", "--quiet", "--initial-branch", "main"),
        ("git", "add", "-A"),
        ("git", "commit", "--quiet", "--message", "base"),
    ):
        run_command(argv, cwd=repo, timeout_s=_GIT_BUDGET_S, env=env, check=True)
    head = run_command(
        ("git", "rev-parse", "HEAD"), cwd=repo, timeout_s=_GIT_BUDGET_S, env=env, check=True
    )
    return repo, head.stdout.strip()


def test_a_tool_that_edits_a_test_file_shows_it_in_the_diff_and_scores_failed(
    tmp_path: Path,
) -> None:
    """The witness for ADR-0038, over real git and a real worktree.

    The pre-razor design excluded test paths from the harvest with a pathspec, so a tool that
    weakened the failing assertion had that edit *removed from the record*, the source half was
    scored on its own, and the trial minted a confident false ``PASSED``. Here the stub tool
    edits both halves; the diff has to hold both, and the trial has to score ``FAILED`` - which
    it can only do through ADR-0037's refusal, because the runner below would answer green.
    """
    repo, head = _real_repo(tmp_path)
    history = GitHistory(repo, worktree_root=tmp_path / "worktrees")
    task = _task().model_copy(update={"base_commit": head, "test_patch": _REAL_TEST_PATCH})
    factory = _RecordingFactory(_ScriptedRunner(_green()))
    adapter = _adapter(_StubTool())

    with history.worktree(head) as workspace:
        attempt = adapter.run(task, workspace, _budget(), trial_index=_TRIAL_INDEX)

    assert attempt.error is None, attempt.error
    assert _SOURCE_FILE in attempt.diff
    assert _TEST_FILE in attempt.diff

    result = run_trial(
        task=task,
        adapter=_Replaying(attempt),
        budget=_budget(),
        history=history,
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.FAILED
    assert factory.workspaces == []


class _Replaying:
    """An ``Adapter`` that returns an attempt already produced, so a trial can score it.

    The witness above runs the real adapter once, inside a worktree it controls, and then asks
    ``run_trial`` what that attempt scores. Replaying it is what keeps the two halves honest:
    the diff scored is byte for byte the diff harvested.
    """

    name: str = "agentic"
    version: str = "replay"

    def __init__(self, attempt: Attempt) -> None:
        self._attempt = attempt
        self.version = attempt.adapter_version

    def run(self, task: Task, workspace: Path, budget: Budget, *, trial_index: int) -> Attempt:
        return self._attempt
