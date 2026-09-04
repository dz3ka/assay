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

M3 is the first milestone whose diffs are written by a model rather than replayed from a
commit, and two rules here exist only because of that. The tool and the measurement work in
*separate* checkouts of the same prepared state (ADR-0038), so the only thing that crosses
from one to the other is the diff the attempt recorded - a tool that installed a package,
wrote a cache or left a stray file cannot change what the scoring run sees. And a diff that
names a test path is refused before it is applied (ADR-0037): rewriting the failing test is
the cheapest way to a green run, and it is the one answer this harness must never score
``PASSED``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from assay.adapters import Adapter
from assay.core import AssayError
from assay.mine.candidates import is_test_path
from assay.mine.models import TestReport
from assay.mine.protocols import History, RunnerFactory
from assay.results import Attempt, Budget, Outcome, Result
from assay.score.executable import score_report
from assay.suite import Task

# The lines of a unified diff that name a path. ``---``/``+++`` cover every content change;
# the rename and copy pairs cover a git diff that moves a file without touching its contents,
# which carries no ``---``/``+++`` header at all and would otherwise pass unread. Content
# lines are not among them on purpose: an added line *mentioning* a test file is source, and
# refusing it would fail trials for citing the test they were asked to satisfy.
_PATH_LINES = ("--- ", "+++ ", "rename from ", "rename to ", "copy from ", "copy to ")

# ``diff --git a/<old> b/<new>``. The two paths are separated by a space and may themselves
# contain one, which git leaves ambiguous, so every whitespace-separated piece is read as a
# candidate rather than the header parsed. A fragment of a path is not a path and matches
# nothing; a whole one matches, which is the direction this rule is allowed to be wrong in.
_GIT_HEADER = "diff --git "

# What git writes for the absent side of an added or deleted file. It names no path in the
# repository and must not be read as one.
_DEV_NULL = "/dev/null"

# The prefixes ``git diff`` puts on the two sides of a change (``--src-prefix``/``--dst-prefix``
# can change them, and a diff that did is read as naming an unprefixed path - which is the
# refusing direction for a test path and a no-op for anything else).
_DIFF_PREFIXES = ("a/", "b/")


class TrialSetupError(AssayError):
    """The workspace could not be brought to the state the trial is defined on.

    Raised when the task's own test patch does not apply at its recorded base commit. A
    validated suite guarantees it does - the red->green gate applied this patch to this
    parent and watched it hold - so a refusal here is a broken suite or harness, never the
    tool under evaluation. That is why it is an error rather than an ``Outcome``: scoring
    the tool ``FAILED`` would charge it for a defect it had no part in, and every mis-set-up
    trial would drag its pass rate toward the null adapter's floor unremarked.

    A trial prepares two workspaces (ADR-0038) and this means the same thing in both. The
    second refusing where the first held is stranger still - the same patch at the same
    commit answered differently - but it is the same class of fault, and measuring a tree
    that is not the task's base state would report a verdict about something else.
    """


def run_trial(
    *,
    task: Task,
    adapter: Adapter,
    budget: Budget,
    history: History,
    runner_for: RunnerFactory,
    timeout_s: int,
    trial_index: int,
) -> Result:
    """Run ``adapter`` against ``task`` once and write the trial down as a :class:`Result`.

    The tool works in one prepared workspace and the measurement happens in another, entered
    after the first is gone (ADR-0038). Both are the same state by construction - the base
    commit plus the task's own test patch - so the diff the attempt carries applies in the
    second exactly as it would have in the first, and the *only* thing that survives the
    handover is that diff. Anything else the tool left in its tree, from a stray file to an
    installed package to a `pytest` cache, is discarded with the worktree rather than
    silently becoming part of what is scored. The second preparation is skipped entirely when
    the attempt reports an error, because nothing is measured then anyway.

    Each worktree is destroyed on the way out whatever happens, exactly as in the miner's
    ``run_gate``: cleanup belongs to the seam (``History.worktree`` is a context manager for
    this reason), not to this function.

    ``trial_index`` is which of the task's n trials this call is, 0-based, and it is the
    caller's to decide: the adapter is told, and the result is named from the argument rather
    than from whatever the attempt came back claiming (ADR-0033).

    Raises:
        TrialSetupError: if the task's test patch does not apply at its base commit, in
            either preparation.
        pydantic.ValidationError: if the adapter's attempt names a different trial than the
            one this call drove; refusing it here keeps a measurement from being attributed
            to a trial that did not produce it (SPEC §5.5).
    """
    with _prepared(history, task) as workspace:
        attempt = adapter.run(task, workspace, budget, trial_index=trial_index)
    if attempt.error is not None:
        return _result(task, adapter, attempt, Outcome.ERRORED, trial_index=trial_index)
    with _prepared(history, task) as workspace:
        report = _measure(
            task=task,
            workspace=workspace,
            diff=attempt.diff,
            history=history,
            runner_for=runner_for,
            timeout_s=timeout_s,
        )
    return _result(task, adapter, attempt, score_report(task, report), trial_index=trial_index)


@contextmanager
def _prepared(history: History, task: Task) -> Iterator[Path]:
    """A workspace at the task's base commit with the task's own test patch applied.

    The state SPEC §3 defines a trial on, and the state both of a trial's workspaces are in:
    the recorded base checkout with the failing tests present and nothing else changed. It is
    a context manager because ``History.worktree`` is one - the checkout is removed on the way
    out however the block ends - and it is a function because it is now entered twice per
    trial, and two spellings of "prepared" could drift into two different states, which would
    make a diff harvested from the first fail to apply in the second for a reason no verdict
    would explain.
    """
    with history.worktree(task.base_commit) as workspace:
        if not history.apply_patch(workspace, task.test_patch):
            raise TrialSetupError(
                f"test patch for task {task.task_id} did not apply "
                f"at its base commit {task.base_commit}"
            )
        yield workspace


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

    A diff that names a test path is refused first, before anything is applied and before a
    runner exists (ADR-0037). Rewriting the failing test is the cheapest route to a green run
    and the one this harness must never reward: the tests are the measurement, so a tool that
    edits them has changed the question rather than answered it, and the resulting ``PASSED``
    would be a confident number nobody should trust. The refusal lives here rather than in
    each adapter because there is exactly one place every present and future adapter's diff
    passes through, and two copies of the rule would be one adapter away from being one.

    The attempt diff is applied only when it is non-empty. ``git apply`` refuses empty
    input, and ``""`` is the null adapter's whole output - the floor every real result is
    read against (CLAUDE.md) - so the empty diff must reach the tests unapplied and score on
    their evidence, not be turned into a patch failure by a quirk of git's argument
    handling. A non-empty diff that does not apply, and a workspace no runner can be made
    for, both return ``None`` without running anything: :func:`score_report` scores both
    ``FAILED``, and skipping the runner means no container is started for a trial that has
    nothing left to measure.
    """
    if _touches_test_path(diff, task):
        return None
    if diff and not history.apply_patch(workspace, diff):
        return None
    runner = runner_for(workspace)
    if runner is None:
        return None
    selectors = (*task.fail_to_pass, *task.pass_to_pass)
    return runner.run(workspace, selectors, timeout_s=timeout_s)


def _touches_test_path(diff: str, task: Task) -> bool:
    """Whether ``diff`` names a path that is part of what the trial measures.

    A test path is :func:`assay.mine.candidates.is_test_path`'s rule - pytest's discovery
    convention plus any path under a ``test``/``tests`` directory (ADR-0032) - *united with*
    the task's own declared ``test_files``. Each half covers what the other misses. The
    declared list names exactly the files the commit changed and no more, so it says nothing
    about a *new* root ``conftest.py``, a ``pytest.ini`` written under ``tests/``, or an edit
    to a test file this task never touched, each of which changes what the recorded ids mean.
    The convention in turn knows nothing about a repository whose tests live somewhere it
    would not look, which is precisely the case the task's own record settles.

    Pure and total, on text a model wrote: it answers for every string and raises for none,
    because a trial that vanished into an exception would leave a hole in the denominator
    this project reports as its honest half (CLAUDE.md). Being wrong in the refusing
    direction costs one trial scored ``FAILED``; being wrong in the other mints a false
    ``PASSED``, so where the two shapes of a diff are ambiguous - a path containing a space in
    a ``diff --git`` header, a prefix that is not git's own - the reading that refuses wins.

    Only the lines that *name* paths are read. A backslash is normalised to a forward slash
    because the schema refuses a path spelled with one (:mod:`assay.suite.models`), so its
    only appearance here is a diff written against the wrong separator - and reading
    ``tests\\test_widget.py`` as a single opaque file name would let exactly the tampering
    this refuses through on a technicality.
    """
    declared = frozenset(task.test_files)
    for line in diff.splitlines():
        for path in _named_paths(line):
            if path in declared or is_test_path(path):
                return True
    return False


def _named_paths(line: str) -> tuple[str, ...]:
    """The repo-relative paths one line of a diff names, normalised, without ``/dev/null``."""
    if line.startswith(_GIT_HEADER):
        candidates: tuple[str, ...] = tuple(line.removeprefix(_GIT_HEADER).split())
    else:
        prefix = next((prefix for prefix in _PATH_LINES if line.startswith(prefix)), None)
        if prefix is None:
            return ()
        # A unified diff may append a tab-separated timestamp to the path; git does not write
        # one, and every other producer of this format may.
        candidates = (line.split("\t", 1)[0].removeprefix(prefix),)
    return tuple(
        normalised
        for candidate in candidates
        if (normalised := _normalised(candidate)) and normalised != _DEV_NULL
    )


def _normalised(candidate: str) -> str:
    """One diff-header field read as a repo-relative POSIX path, as far as it can be.

    Exactly one of git's two prefixes is removed, never both in turn: a repository really can
    hold a directory called ``b``, and stripping a second time would turn ``a/b/tests`` into
    ``tests`` and lose which file the header named.

    Quotes are stripped rather than decoded: git quotes a path holding a byte outside its
    configured charset and escapes it in place, so the directory segments a test path is
    recognised by survive verbatim even when the file name itself does not.
    """
    path = candidate.strip().strip('"').replace("\\", "/")
    for prefix in _DIFF_PREFIXES:
        if path.startswith(prefix):
            return path.removeprefix(prefix)
    return path


def _result(
    task: Task, adapter: Adapter, attempt: Attempt, outcome: Outcome, *, trial_index: int
) -> Result:
    """The trial written down, named by what the harness drove rather than by the attempt.

    All three names come from this call: the task it set up, the adapter it called and the
    trial it ran. :class:`Result`'s own validator requires the attempt to agree with each of
    them, so a mislabelled attempt is refused loudly here instead of being recorded under
    whichever trial it claimed to be - which is only true of the trial number because the
    number is passed in. Copying it out of ``attempt`` would have made the result agree with
    the attempt by construction, leaving the validator's third clause unreachable and an
    adapter free to file its work under a trial nobody ran (ADR-0033).
    """
    return Result(
        schema_version=1,
        task_id=task.task_id,
        adapter_name=adapter.name,
        trial_index=trial_index,
        attempt=attempt,
        outcome=outcome,
    )
