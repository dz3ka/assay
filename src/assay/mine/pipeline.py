"""The I/O half of mining: worktrees, patches, test runs, and the yield they add up to.

:mod:`assay.mine.gate` holds the *rule* and decides on values alone. This module is what
gathers those values - it walks the history, splits each commit, checks the two halves out
into a throwaway worktree and runs the tests that let :func:`assay.mine.decide_gate` speak
(SPEC §3 steps 1-4, ADR-0002). Everything it touches the outside world with is a
:mod:`assay.mine.protocols` seam, so this module never imports git, uv, pytest or
``subprocess``: what runs is whatever the caller wired in.

**Generators, not callbacks.** Mining a real repository is minutes of work and a CLI has to
say so while it happens. A callback would invert control, put the progress format inside the
miner and make the whole thing untestable without a spy; a generator hands each examined
commit back the moment it is decided, and the caller prints, tallies and stops walking on its
own terms. The stream is also what makes ``limit`` honest: nothing is buffered, so a caller
that stops early has genuinely not paid for the rest.

**The counting contract, which is the honest half of the result** (CLAUDE.md, "report yield,
not just totals"). One examined commit per :class:`~assay.mine.models.CommitRef` the walk
yields - a merge and the root are never yielded and so are never examined, they are outside
this accounting rather than a reason inside it (ADR-0015). One candidate per commit that
reaches the gate's decision; a commit rejected for one of
:data:`~assay.mine.models.PRE_GATE_REJECTIONS`, and a commit whose workspace could not be
provisioned at all, never reach :func:`assay.mine.decide_gate` and so are examined without
being candidates. :func:`tally_yield` is where those rules are spelled, once, so the CLI
cannot count differently from the test that pins the numbers.

**One worktree per candidate, three runs in it.** The red run happens with only the test patch
applied; the ground truth is then applied *in the same tree* and the confirmation runs follow.
That is one checkout and one environment per candidate instead of two, and it is also what
makes a flaky test detectable: two confirmation runs of the same tree are the only
disagreement Assay can see (SPEC §9's flaky fixture is built to exactly this sequence).
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from types import MappingProxyType

from assay.mine.candidates import build_prompt, mint_task_id, pytest_selectors, split_changes
from assay.mine.gate import GREEN_CONFIRMATION_RUNS, decide_gate
from assay.mine.models import (
    PRE_GATE_REJECTIONS,
    ChangeSplit,
    CommitRef,
    GateOutcome,
    GateRejection,
    MiningYield,
)
from assay.mine.protocols import History, RunnerFactory
from assay.suite import SuiteBody, Task


@dataclass(frozen=True)
class MinedCommit:
    """One examined commit: what the gate concluded, and the task if it survived.

    ``outcome`` is ``None`` when the commit's workspace could not be given an environment its
    tests could run in, so the gate never got to speak (see
    :data:`assay.mine.protocols.RunnerFactory`). The invariant, which the CLI and the scorer
    both rely on: ``task is not None`` **iff** ``outcome is not None and outcome.rejection is
    None``.

    The task is carried here rather than rebuilt by the caller because building it needs the
    commit's two patches and its split - values this module already holds and the CLI would
    otherwise have to ask git for a second time, which would put mining logic in the command
    layer.
    """

    commit: CommitRef
    outcome: GateOutcome | None
    task: Task | None


def mine_suite(
    *,
    history: History,
    runner_for: RunnerFactory,
    repo_slug: str,
    limit: int | None,
    timeout_s: int,
) -> Iterator[MinedCommit]:
    """Walk ``history`` newest-first and put every commit it yields through the gate.

    Args:
        history: The repository to mine. Never written to: every checkout is a throwaway
            worktree the seam owns.
        runner_for: Makes the test runner for one workspace, once that workspace exists (see
            :data:`assay.mine.protocols.RunnerFactory`).
        repo_slug: What the mined task ids are named after, normally the repository's
            directory name.
        limit: How many commits to ask the walk for, or ``None`` for all of them.
        timeout_s: The ceiling on **one** test run. Three runs happen per candidate, so this
            is not a budget for the whole gate; it is the point at which a hanging test is
            killed and the candidate is discarded as ``run_timed_out``.

    Yields:
        One :class:`MinedCommit` per examined commit, in the walk's order, as each is decided.
    """
    # Asked once rather than per commit: it is provenance about the repository, not about the
    # commit, and it is the one seam call that would otherwise be paid on every iteration.
    repo_url = history.repo_url()
    for commit in history.commits(limit=limit):
        yield _mine_one(
            history=history,
            runner_for=runner_for,
            repo_url=repo_url,
            repo_slug=repo_slug,
            commit=commit,
            timeout_s=timeout_s,
        )


def revalidate_suite(
    *,
    suite: SuiteBody,
    history: History,
    runner_for: RunnerFactory,
    timeout_s: int,
) -> Iterator[tuple[Task, GateOutcome | None]]:
    """Put every task in ``suite`` back through the byte-identical gate that minted it.

    This is ``assay validate``. A suite is a claim that these commits went red to green, and a
    claim that has stopped being true - an environment that drifted, a dependency that moved -
    is exactly what this project exists to catch before a tool is scored against it. So the
    rule is not re-implemented here; the same :func:`run_gate` runs, from the patches the task
    itself carries rather than from git's answer about a commit.

    Yields:
        One ``(task, outcome)`` pair per task, in the suite's canonical order. Whether a pair
        is *valid* is :func:`assay.mine.revalidates` and nothing weaker - an accepting outcome
        that crossed a different set of tests than the task records is not a revalidation. The
        outcome travels alongside so a caller can say **why** a task failed to revalidate; it
        is not the caller's job to work out **whether** it did.
    """
    for task in suite.tasks:
        # ``run_gate`` reads exactly two things out of these: the state to check out, and the
        # files to point the runner at. A suite records the base state and the test files, and
        # deliberately does not record the commit it was mined from (that is metadata, not
        # identity), so the base commit stands for both halves of the ref here.
        commit = CommitRef(sha=task.base_commit, parent=task.base_commit, subject=task.task_id)
        split = ChangeSplit(test_files=task.test_files, source_files=())
        yield (
            task,
            run_gate(
                history=history,
                runner_for=runner_for,
                commit=commit,
                split=split,
                test_patch=task.test_patch,
                ground_truth_patch=task.ground_truth_patch,
                timeout_s=timeout_s,
            ),
        )


def run_gate(
    *,
    history: History,
    runner_for: RunnerFactory,
    commit: CommitRef,
    split: ChangeSplit,
    test_patch: str,
    ground_truth_patch: str,
    timeout_s: int,
) -> GateOutcome | None:
    """Gather SPEC §3's evidence for one candidate and hand it to :func:`decide_gate`.

    The sequence is the specification's, in order: check the parent out, apply the test patch
    only, prove the tests fail, apply the ground truth, prove they pass - twice, because one
    run cannot tell a fix from a flake.

    The worktree is destroyed on the way out whatever happens, including a patch that would not
    apply and a test run that had to be killed; that cleanup belongs to the seam
    (``History.worktree`` is a context manager for this reason) rather than to this function.

    Returns:
        The gate's verdict, or ``None`` if the workspace could not be given an environment its
        tests could run in. ``None`` is neither a verdict nor an abort: provisioning is per
        commit, so a repository mined back past the commit that introduced its packaging has
        commits that cannot be installed, and a walk that died on the first of them would
        report no yield at all. It is counted as ``MiningYield.unprovisioned``.
    """
    selectors = pytest_selectors(split.test_files)
    with history.worktree(commit.parent) as workspace:
        if not history.apply_patch(workspace, test_patch):
            return _rejected(GateRejection.PATCH_DID_NOT_APPLY)
        # After the patch check, so a candidate that cannot be set up at all does not pay for
        # an environment first: provisioning is seconds per candidate and this is the one
        # rejection that is knowable without it.
        runner = runner_for(workspace)
        if runner is None:
            return None
        red = runner.run(workspace, selectors, timeout_s=timeout_s)
        if red.timed_out:
            # Duplicating ``decide_gate``'s first check on purpose. That rule returns
            # ``run_timed_out`` whatever the confirmation runs say, so running them after a red
            # that timed out buys evidence nothing will read - at a real ``timeout_s`` of 600s,
            # twenty wasted minutes per hanging candidate. Same verdict, a third of the cost.
            return _rejected(GateRejection.RUN_TIMED_OUT)
        if not history.apply_patch(workspace, ground_truth_patch):
            return _rejected(GateRejection.PATCH_DID_NOT_APPLY)
        greens = [
            runner.run(workspace, selectors, timeout_s=timeout_s)
            for _ in range(GREEN_CONFIRMATION_RUNS)
        ]
    return decide_gate(red, greens)


def tally_yield(outcomes: Iterable[GateOutcome | None]) -> MiningYield:
    """Add a completed run's outcomes up into the line CLAUDE.md requires every report to carry.

    One outcome per examined commit - including a ``None``, which is a commit the walk yielded
    and no gate spoke about - so ``commits_examined`` is simply how many there were.
    Every reason appears in ``rejected``, zeros included: a sparse mapping would make "this
    reason never fired" and "this reason was not looked for" the same document, and telling
    those apart is the whole of yield honesty (ADR-0015 is the same argument applied to a
    reason that could never fire at all).

    The identities this arithmetic has to satisfy are not enforced here: they are
    :class:`MiningYield`'s own validator, so a yield read back from a file is refusable on the
    same terms as one counted in process (ADR-0011).
    """
    decided = tuple(outcomes)
    judged = tuple(outcome for outcome in decided if outcome is not None)
    return MiningYield(
        commits_examined=len(decided),
        candidates=sum(1 for outcome in judged if outcome.rejection not in PRE_GATE_REJECTIONS),
        accepted=sum(1 for outcome in judged if outcome.rejection is None),
        rejected=MappingProxyType(
            {
                reason: sum(1 for outcome in judged if outcome.rejection is reason)
                for reason in GateRejection
            }
        ),
        unprovisioned=len(decided) - len(judged),
    )


def _mine_one(
    *,
    history: History,
    runner_for: RunnerFactory,
    repo_url: str,
    repo_slug: str,
    commit: CommitRef,
    timeout_s: int,
) -> MinedCommit:
    """Decide one examined commit, running the gate only if its diff is worth running."""
    split = split_changes(history.changed_paths(commit.parent, commit.sha))
    if not pytest_selectors(split.test_files):
        # Includes the commit whose test half is real but holds nothing a runner can be
        # pointed at - a fixture data file on its own. There is no red run to be had, so it is
        # the same discard as a commit that touched no test at all.
        return MinedCommit(commit, _rejected(GateRejection.NO_TEST_CHANGES), None)
    if not split.source_files:
        return MinedCommit(commit, _rejected(GateRejection.NO_SOURCE_CHANGES), None)

    test_patch = history.diff(commit.parent, commit.sha, split.test_files)
    ground_truth_patch = history.diff(commit.parent, commit.sha, split.source_files)
    outcome = run_gate(
        history=history,
        runner_for=runner_for,
        commit=commit,
        split=split,
        test_patch=test_patch,
        ground_truth_patch=ground_truth_patch,
        timeout_s=timeout_s,
    )
    task = (
        None
        if outcome is None or outcome.rejection is not None
        else _task(
            repo_url=repo_url,
            repo_slug=repo_slug,
            commit=commit,
            split=split,
            test_patch=test_patch,
            ground_truth_patch=ground_truth_patch,
            outcome=outcome,
        )
    )
    return MinedCommit(commit, outcome, task)


def _task(
    *,
    repo_url: str,
    repo_slug: str,
    commit: CommitRef,
    split: ChangeSplit,
    test_patch: str,
    ground_truth_patch: str,
    outcome: GateOutcome,
) -> Task:
    """Write down the task the gate just proved, in the schema a suite is built from.

    ``base_commit`` is the *parent*: a task is the repository as it stood before the fix, which
    is the state a tool under evaluation is handed (SPEC §3 step 2). The commit the task was
    mined from is provenance, so it travels in ``metadata`` where a human reads it and nothing
    depends on it.
    """
    return Task(
        schema_version=1,
        task_id=mint_task_id(repo_slug, commit.sha),
        repo_url=repo_url,
        base_commit=commit.parent,
        test_files=split.test_files,
        test_patch=test_patch,
        ground_truth_patch=ground_truth_patch,
        fail_to_pass=outcome.fail_to_pass,
        pass_to_pass=outcome.pass_to_pass,
        prompt=build_prompt(commit.subject, split, outcome.fail_to_pass),
        metadata=MappingProxyType(
            {"mined_from_commit": commit.sha, "commit_subject": commit.subject}
        ),
    )


def _rejected(rejection: GateRejection) -> GateOutcome:
    """A discard, with both scored sets empty - the shape ``decide_gate`` also returns."""
    return GateOutcome(rejection=rejection, fail_to_pass=(), pass_to_pass=())
