"""What Assay is allowed to believe about a repository it did not write.

These tests run against real repositories built by real ``git init`` under ``tmp_path``,
because the properties worth defending here are git's behaviour and not a mock's: that a
merge is not a mineable commit, that a worktree leaves the user's clone exactly as it found
it, that a patch which does not apply is an answer rather than an exception, and that a path
git reports is refused before it can become an argument or a filesystem path.

Every fixture repository pins identity and line endings, because the dev host is Windows and
CI is Linux and a commit made under ``core.autocrlf=true`` would produce a different diff on
each (codebase map, "Windows dev host vs ubuntu-latest CI").
"""

import os
import subprocess
from pathlib import Path

import pytest

from assay.host import GitError, GitHistory
from assay.mine.protocols import History

# Identity and line endings on every invocation, so a fixture repository does not depend on
# the ~/.gitconfig of whoever is running the suite.
_PINNED = (
    "-c",
    "user.name=Assay Test",
    "-c",
    "user.email=assay@example.invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.eol=lf",
)

_BASE_SOURCE = "def add(a, b):\n    return 0\n"
_FIXED_SOURCE = "def add(a, b):\n    return a + b\n"


def _git(repo: Path, *arguments: str, when: str | None = None) -> str:
    """Drive git directly, so the fixtures do not depend on the module under test.

    ``when`` pins both timestamps of a commit. Without it two commits made in the same second
    tie, and `git log`'s newest-first order stops being a fact the fixture can assert.
    """
    environment = dict(os.environ)
    if when is not None:
        environment["GIT_AUTHOR_DATE"] = when
        environment["GIT_COMMITTER_DATE"] = when
    completed = subprocess.run(
        ["git", *_PINNED, *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=environment,
    )
    return completed.stdout


def _write(repo: Path, name: str, text: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _commit(repo: Path, message: str, *, when: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message, when=when)
    return _git(repo, "rev-parse", "HEAD").strip()


def _history(tmp_path: Path) -> tuple[GitHistory, Path]:
    """A repository with a root commit, a fix commit, a side branch and a merge.

    The merge is there so "``--no-merges``, single parent" is a property with a witness
    rather than a flag nobody exercises.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")

    _write(repo, "src/app.py", _BASE_SOURCE)
    _write(repo, "tests/test_app.py", "from src.app import add\n\n\ndef test_add():\n    pass\n")
    _write(repo, "README.md", "fixture\n")
    _commit(repo, "root: the state before anything is mineable", when="2024-01-01T00:00:01+00:00")

    _write(repo, "src/app.py", _FIXED_SOURCE)
    _write(
        repo,
        "tests/test_app.py",
        "from src.app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    _commit(repo, "fix: add actually adds", when="2024-01-01T00:00:02+00:00")

    _git(repo, "checkout", "-b", "side")
    _write(repo, "README.md", "fixture, from the side branch\n")
    _commit(repo, "docs: a commit on a branch", when="2024-01-01T00:00:03+00:00")
    _git(repo, "checkout", "main")
    _git(
        repo,
        "merge",
        "--no-ff",
        "-m",
        "merge: side into main",
        "side",
        when="2024-01-01T00:00:04+00:00",
    )

    return GitHistory(repo, worktree_root=tmp_path / "worktrees"), repo


def _subjects(history: GitHistory, *, limit: int | None = None) -> list[str]:
    return [commit.subject for commit in history.commits(limit=limit)]


def test_git_history_satisfies_the_history_protocol(tmp_path: Path) -> None:
    # Proved statically by `mypy --strict`, the way `Adapter` conformance is proved in
    # `tests/adapters/test_ground_truth.py`: structural typing, no base class, and no
    # `isinstance` check that would only ask whether the names exist.
    conformant: History = GitHistory(tmp_path, worktree_root=tmp_path / "worktrees")

    assert conformant is not None


def test_the_walk_skips_merges_and_the_parentless_root(tmp_path: Path) -> None:
    history, _ = _history(tmp_path)

    subjects = _subjects(history)

    assert subjects == ["docs: a commit on a branch", "fix: add actually adds"]


def test_every_commit_names_the_single_parent_it_is_read_against(tmp_path: Path) -> None:
    history, repo = _history(tmp_path)

    fix = next(commit for commit in history.commits(limit=None) if commit.subject.startswith("fix"))

    assert fix.parent == _git(repo, "rev-parse", f"{fix.sha}^").strip()
    assert fix.sha != fix.parent


def test_the_walk_stops_at_the_limit_it_was_given(tmp_path: Path) -> None:
    history, _ = _history(tmp_path)

    assert _subjects(history, limit=1) == ["docs: a commit on a branch"]


def test_changed_paths_are_the_files_the_commit_touched(tmp_path: Path) -> None:
    history, _ = _history(tmp_path)
    fix = next(commit for commit in history.commits(limit=None) if commit.subject.startswith("fix"))

    assert history.changed_paths(fix.parent, fix.sha) == ("src/app.py", "tests/test_app.py")


def test_a_diff_carries_only_the_paths_it_was_restricted_to(tmp_path: Path) -> None:
    # This restriction is the red-green gate's whole mechanism: the test half of a commit is
    # applied and proved red before the source half is applied at all (SPEC §3).
    history, _ = _history(tmp_path)
    fix = next(commit for commit in history.commits(limit=None) if commit.subject.startswith("fix"))

    patch = history.diff(fix.parent, fix.sha, ["tests/test_app.py"])

    assert "tests/test_app.py" in patch
    assert "src/app.py" not in patch


def test_repo_url_is_the_origin_remote_when_the_clone_has_one(tmp_path: Path) -> None:
    history, repo = _history(tmp_path)
    _git(repo, "remote", "add", "origin", "https://example.invalid/fixture.git")

    assert history.repo_url() == "https://example.invalid/fixture.git"


def test_repo_url_falls_back_to_the_local_path_rather_than_fetching(tmp_path: Path) -> None:
    # Assay never clones and never fetches (SPEC §5.1); a repository with no remote is a
    # perfectly ordinary thing to mine, and it still has to be nameable in a task.
    history, repo = _history(tmp_path)

    assert history.repo_url() == str(repo)


def test_a_worktree_holds_the_commit_and_is_removed_and_pruned_afterwards(tmp_path: Path) -> None:
    history, repo = _history(tmp_path)
    fix = next(commit for commit in history.commits(limit=None) if commit.subject.startswith("fix"))

    with history.worktree(fix.parent) as workspace:
        assert (workspace / "src" / "app.py").read_text(encoding="utf-8") == _BASE_SOURCE
        assert workspace.as_posix() in _git(repo, "worktree", "list")

    assert not workspace.exists()
    assert workspace.as_posix() not in _git(repo, "worktree", "list")


def test_a_worktree_is_removed_even_when_the_body_raises(tmp_path: Path) -> None:
    history, repo = _history(tmp_path)
    fix = next(commit for commit in history.commits(limit=None) if commit.subject.startswith("fix"))

    with (
        pytest.raises(RuntimeError, match="the mined tests exploded"),
        history.worktree(fix.sha) as workspace,
    ):
        raise RuntimeError("the mined tests exploded")

    assert not workspace.exists()
    assert workspace.as_posix() not in _git(repo, "worktree", "list")


def test_the_users_clone_is_never_checked_out_or_dirtied(tmp_path: Path) -> None:
    history, repo = _history(tmp_path)
    fix = next(commit for commit in history.commits(limit=None) if commit.subject.startswith("fix"))
    head = _git(repo, "rev-parse", "HEAD").strip()

    with history.worktree(fix.parent) as workspace:
        (workspace / "src" / "app.py").write_text("scribbled\n", encoding="utf-8", newline="\n")

    assert _git(repo, "rev-parse", "HEAD").strip() == head
    assert _git(repo, "status", "--porcelain") == ""


def test_a_commits_own_patch_applies_to_a_checkout_of_its_parent(tmp_path: Path) -> None:
    history, _ = _history(tmp_path)
    fix = next(commit for commit in history.commits(limit=None) if commit.subject.startswith("fix"))
    patch = history.diff(fix.parent, fix.sha, ["src/app.py"])

    with history.worktree(fix.parent) as workspace:
        applied = history.apply_patch(workspace, patch)
        content = (workspace / "src" / "app.py").read_text(encoding="utf-8")

    assert applied is True
    assert content == _FIXED_SOURCE


def test_a_patch_that_does_not_apply_is_refused_without_raising(tmp_path: Path) -> None:
    # `git apply --check` before `git apply`, so the tree is never half-patched. A commit
    # whose diff will not apply to its parent is discarded and counted, not an incident.
    history, _ = _history(tmp_path)
    fix = next(commit for commit in history.commits(limit=None) if commit.subject.startswith("fix"))
    patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-a line this file has never contained\n"
        "+something else\n"
    )

    with history.worktree(fix.parent) as workspace:
        applied = history.apply_patch(workspace, patch)
        content = (workspace / "src" / "app.py").read_text(encoding="utf-8")

    assert applied is False
    assert content == _BASE_SOURCE


def test_applying_a_patch_leaves_no_scratch_file_in_the_workspace(tmp_path: Path) -> None:
    # The workspace is what a trial is scored from, so anything Assay writes into it would be
    # counted as the tool's output.
    history, _ = _history(tmp_path)
    fix = next(commit for commit in history.commits(limit=None) if commit.subject.startswith("fix"))
    patch = history.diff(fix.parent, fix.sha, ["src/app.py"])

    with history.worktree(fix.parent) as workspace:
        history.apply_patch(workspace, patch)
        untracked = _git(workspace, "status", "--porcelain", "--untracked-files=all")

    assert untracked.strip() == "M src/app.py"


@pytest.mark.parametrize(
    "hostile",
    [
        "a\0b",
        "src\\app.py",
        "/etc/passwd",
        "../../../etc/passwd",
        "src/../../secrets",
        "C:/Windows/System32",
        "--output=/tmp/owned",
        "",
    ],
    ids=[
        "nul-byte",
        "backslash",
        "leading-slash",
        "parent-segments",
        "interior-parent-segment",
        "drive-letter",
        "option-lookalike",
        "empty",
    ],
)
def test_a_path_that_could_escape_the_repository_is_refused_loudly(
    tmp_path: Path, hostile: str
) -> None:
    # Loudly, not silently: skipping the path would leave a task whose diff is missing a
    # file, which is a wrong measurement rather than a missing one.
    history, _ = _history(tmp_path)
    fix = next(commit for commit in history.commits(limit=None) if commit.subject.startswith("fix"))

    with pytest.raises(GitError):
        history.diff(fix.parent, fix.sha, [hostile])


@pytest.mark.parametrize(
    "hostile",
    ["--output=/tmp/owned", "main", "HEAD", "; rm -rf /", "", "zzzzzzz"],
    ids=["option", "branch-name", "head", "shell-ish", "empty", "not-hex"],
)
def test_a_revision_that_is_not_an_object_name_is_refused(tmp_path: Path, hostile: str) -> None:
    history, _ = _history(tmp_path)
    fix = next(commit for commit in history.commits(limit=None) if commit.subject.startswith("fix"))

    with pytest.raises(GitError):
        history.changed_paths(hostile, fix.sha)

    with pytest.raises(GitError):
        history.worktree(hostile).__enter__()


def test_a_failing_git_command_surfaces_as_a_git_error(tmp_path: Path) -> None:
    empty = tmp_path / "not-a-repo"
    empty.mkdir()
    history = GitHistory(empty, worktree_root=tmp_path / "worktrees")

    with pytest.raises(GitError):
        list(history.commits(limit=None))
