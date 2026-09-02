"""The tripwire on the fixture git repository: it is the same repository everywhere (SPEC §9).

``tests/fixture_repo.py`` builds the history M1's end-to-end test mines for an *exact* yield.
That assertion is only worth anything while the repository being mined is the one the yield
was computed from, so the commit object names are pinned and asserted here. The dev host is
Windows and CI is ubuntu-latest: a line ending, a file mode or a stray ``GIT_*`` variable that
differed between them would build a different history on each, and every downstream assertion
would quietly become a statement about a different repository. This test is the canary for
that, and it is meant to fail on the first Linux run rather than to be relaxed.

The rest of the file pins what can be checked without running a test suite: that the eight
``GateRejection`` reasons all have a commit in the history, that the walk yields the eleven
commits :data:`EXPECTED_YIELD` counts, and that the three reasons decided on the diff alone -
no test changes, no source changes, patch did not apply - really are reached. The five that
need pytest belong to the end-to-end mining test, which runs the suite this history carries.
"""

from pathlib import Path

import pytest

from assay.host import GitHistory
from assay.mine import CommitRef, GateRejection, split_changes
from tests.fixture_repo import EXPECTED_YIELD, FIXTURE_COMMITS, FixtureCommit, build_fixture_repo


def _by_label(label: str) -> FixtureCommit:
    return next(commit for commit in FIXTURE_COMMITS if commit.label == label)


def _history(tmp_path: Path) -> GitHistory:
    """Build the fixture and read it back through the same class the miner uses."""
    repo = build_fixture_repo(tmp_path / "build")
    return GitHistory(repo, worktree_root=tmp_path / "worktrees")


def _walked(history: GitHistory, label: str) -> CommitRef:
    """The walk's own view of one labelled commit, so its parent is a sha and not ``sha^``.

    ``GitHistory`` refuses any revision that is not an object name (``_checked_revision``), so
    a test may not say "the parent of" in git's shorthand; it asks the walk, exactly as the
    miner does.
    """
    sha = _by_label(label).sha
    return next(commit for commit in history.commits(limit=None) if commit.sha == sha)


def test_the_history_builds_to_the_pinned_object_names(tmp_path: Path) -> None:
    # The canary. `build_fixture_repo` also checks this itself, so that a caller which is not
    # this test still refuses a repository that has drifted; asserting it here as well is what
    # makes the drift a named failure rather than an oblique one somewhere downstream.
    repo = build_fixture_repo(tmp_path)

    history = GitHistory(repo, worktree_root=tmp_path / "worktrees")
    walked = {commit.sha for commit in history.commits(limit=None)}

    assert walked == {commit.sha for commit in FIXTURE_COMMITS if commit.walked}


def test_every_rejection_reason_has_a_commit_that_reaches_it() -> None:
    # The binding rule behind the fixture: a reason with no commit behind it is speculative,
    # and a speculative reason is a hole in the yield accounting the whole project rests on.
    # "Reaches it" means a commit the walk actually *yields*: a reason witnessed only by a
    # commit git never hands over is not reachable at all, which is how `merge_commit` stayed
    # in the enum until ADR-0015 cut it. Hence the `walked` filter.
    covered = {
        commit.rejection
        for commit in FIXTURE_COMMITS
        if commit.walked and commit.rejection is not None
    }

    assert covered == set(GateRejection)


def test_the_expected_yield_is_the_arithmetic_of_the_commit_table() -> None:
    # Pinned rather than only derived: CLAUDE.md says a change in the yield is a deliberate
    # decision with an ADR behind it, so editing the table has to break something.
    assert EXPECTED_YIELD.commits_examined == 11
    assert EXPECTED_YIELD.candidates == 7
    assert EXPECTED_YIELD.accepted == 2
    assert EXPECTED_YIELD.accepted + sum(EXPECTED_YIELD.rejected.values()) == 11
    # Every reason is reported, zeros included, so a yield is a full partition rather than a
    # sparse mapping whose missing keys a reader has to guess the meaning of.
    assert set(EXPECTED_YIELD.rejected) == set(GateRejection)
    assert len(EXPECTED_YIELD.rejected) == 8


def test_the_walk_yields_the_eleven_commits_the_yield_counts(tmp_path: Path) -> None:
    # `commits_examined` is the denominator of the only number this project reports, so it is
    # asserted against git rather than against the table that claims it.
    history = _history(tmp_path)

    walked = list(history.commits(limit=None))

    assert len(walked) == EXPECTED_YIELD.commits_examined
    assert [commit.subject for commit in walked] == [
        commit.subject for commit in reversed(FIXTURE_COMMITS) if commit.walked
    ]


def test_the_merge_commit_is_in_the_history_but_is_never_examined(tmp_path: Path) -> None:
    # A merge is not a rejection reason, it is a commit outside the accounting: git drops it
    # before Assay sees it, so it is never examined and never counted (ADR-0015). The commit
    # is in the fixture so the claim has a witness.
    history = _history(tmp_path)
    merge = _by_label("merge_tidy")

    walked = {commit.sha for commit in history.commits(limit=None)}

    assert merge.walked is False
    assert merge.rejection is None
    assert merge.sha not in walked


@pytest.mark.parametrize(
    ("label", "reason"),
    [
        ("fixed_field_parse", GateRejection.NO_TEST_CHANGES),
        ("deterministic_jitter", GateRejection.NO_SOURCE_CHANGES),
        ("repair_conftest_units", GateRejection.NO_SOURCE_CHANGES),
    ],
    ids=["a fix with no test", "a test tidy-up with no fix", "a conftest repair with no fix"],
)
def test_a_one_sided_commit_splits_into_one_empty_half(
    tmp_path: Path, label: str, reason: GateRejection
) -> None:
    history = _history(tmp_path)
    commit = _walked(history, label)

    split = split_changes(history.changed_paths(commit.parent, commit.sha))

    assert _by_label(label).rejection is reason
    empty = split.test_files if reason is GateRejection.NO_TEST_CHANGES else split.source_files
    populated = split.source_files if reason is GateRejection.NO_TEST_CHANGES else split.test_files
    assert empty == ()
    assert populated != ()


def test_the_binary_fixture_commit_has_a_test_patch_that_will_not_apply(tmp_path: Path) -> None:
    # `GitHistory.diff` does not pass `--binary`, so a commit carrying a binary file under
    # tests/ produces "Binary files ... differ" with an abbreviated index line, which
    # `git apply` refuses. That is a real limit on what M1 can mine, and it is the only way
    # `patch_did_not_apply` is reached from a well-formed history - so it is pinned here
    # rather than left to be rediscovered as a mysterious drop in yield.
    history = _history(tmp_path)
    commit = _walked(history, "payload_format_two")
    split = split_changes(history.changed_paths(commit.parent, commit.sha))

    patch = history.diff(commit.parent, commit.sha, split.test_files)
    with history.worktree(commit.parent) as workspace:
        applied = history.apply_patch(workspace, patch)

    assert _by_label("payload_format_two").rejection is GateRejection.PATCH_DID_NOT_APPLY
    assert "tests/data/sample.bin" in split.test_files
    assert applied is False
