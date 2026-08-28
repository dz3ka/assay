"""Every git question M1 asks, answered without ever trusting the answer's shape.

Mining reads a repository's own history (ADR-0002), and that history is attacker-controlled
in the only sense that matters: a path in a commit is whatever the committer typed, and it
arrives here on its way to an argv or a :class:`~pathlib.Path`. So every path git hands back
passes :func:`_checked_path` before it is used, and a rejected path is a :class:`GitError`
rather than a quiet skip - a task built from a half-read commit would be a measurement about
nothing (CLAUDE.md, "report yield, not just totals": a refusal has to be countable).

Two blast-radius rules are structural rather than advisory. Checkouts happen in a throwaway
``git worktree`` under ``worktree_root``, so nothing here can dirty the user's clone; and
Assay never clones or fetches, so ``repo`` is a path that already existed and ``repo_url`` is
a label rather than a network operation (SPEC §5.1 - the repository never leaves the machine).

This class satisfies the ``History`` protocol structurally, the way the M0 adapters satisfy
``Adapter`` (:mod:`assay.adapters.protocol`): no base class, conformance proved by mypy at the
one place a ``History`` is annotated.
"""

import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from assay.core import AssayError
from assay.host.process import CommandResult, minimal_env, run_command
from assay.mine.models import CommitRef

# Config forced onto every invocation, ahead of anything the user's ``~/.gitconfig`` says.
# ``core.quotePath=false`` makes git print a non-ASCII path as raw UTF-8 instead of as
# C-style escapes, so the allowlist below inspects the real name rather than a rendering of
# it. The line-ending pair keeps a diff byte-identical between the Windows dev host and the
# Linux CI: a patch mined with autocrlf on would not apply where it was mined from.
_CONFIG_FLAGS: Final = (
    "-c",
    "core.quotePath=false",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.eol=lf",
)

# Field and record separators for ``git log``. A commit subject is free text and may contain
# anything a keyboard emits, so the parse splits on bytes a subject cannot carry rather than
# on whitespace, and caps the split so a subject holding the separator cannot forge a field.
_FIELD_SEPARATOR: Final = "\x1f"
_LOG_FORMAT: Final = f"%H{_FIELD_SEPARATOR}%P{_FIELD_SEPARATOR}%s"

# A revision reaching an argv is either a full object name or an abbreviation of one. Nothing
# else - a branch name or a ``--flag`` would both be arguments Assay did not mean to pass.
_REVISION_PATTERN: Final = re.compile(r"^[0-9a-fA-F]{7,40}$")

# Plumbing (log, diff, remote) answers in milliseconds on any repository a laptop holds; a
# checkout writes a whole tree to disk. Both are ceilings on a hang, not budgets to spend.
_QUERY_TIMEOUT_S: Final = 60
_CHECKOUT_TIMEOUT_S: Final = 300


class GitError(AssayError):
    """Git refused, or answered with something Assay will not pass on.

    Both halves matter. A failed command is the ordinary case; a path with a ``..`` segment in
    it is the interesting one, and it is an error here rather than a filtered-out row because
    "this repository contains a commit Assay cannot mine safely" is a finding.
    """


class GitHistory:
    """Read-only access to one local repository, plus disposable checkouts of it.

    Args:
        repo: An existing local clone. Assay never creates it and never fetches into it.
        worktree_root: A temporary directory that every checkout is made under. Created on
            first use; each worktree is removed and pruned when its context manager exits.
    """

    def __init__(self, repo: Path, *, worktree_root: Path) -> None:
        self._repo = repo
        self._worktree_root = worktree_root
        # Built once, read-only from here: the environment a git child sees. The terminal
        # prompt is disabled because a credential prompt on a hidden stdin is a hang, and a
        # hang inside mining is indistinguishable from a slow repository.
        self._env: Final = {**minimal_env(), "GIT_TERMINAL_PROMPT": "0"}

    def repo_url(self) -> str:
        """Name the repository: its ``origin`` remote if it has one, else its local path.

        Never a network operation. The value ends up in ``Task.repo_url`` as provenance, and
        a repository with no remote is a perfectly good thing to mine (SPEC §5.1).
        """
        found = self._git("remote", "get-url", "origin", check=False)
        url = found.stdout.strip()
        return url if found.exit_code == 0 and url else str(self._repo)

    def commits(self, *, limit: int | None) -> Iterator[CommitRef]:
        """Walk history newest-first, yielding only commits that have exactly one parent.

        A mined task is a commit read against *the* state before it (ADR-0002), so a commit
        without exactly one parent is not a candidate. ``--no-merges`` drops the many-parent
        case; the root commit has no parent and is skipped here. Neither is a refusal - a
        repository's first commit is not an anomaly, it is the end of the walk. A record this
        walk does not yield is not *examined* either, so it sits outside the yield accounting
        rather than inside it as a reason (ADR-0015).

        ``limit`` bounds what git prints, so a walk that reaches the root commit yields one
        fewer than it asked for. The walk is materialised before the first item, because
        :func:`assay.host.run_command` is a batch API by design - one bounded process, then
        all of its output - and ``limit`` is what keeps that bounded on a long history.
        """
        argv = ["log", "--no-merges", "-z", f"--format={_LOG_FORMAT}"]
        if limit is not None:
            argv += ["--max-count", str(limit)]
        found = [_parse_commit(record) for record in _records(self._git(*argv).stdout)]
        return iter([commit for commit in found if commit is not None])

    def changed_paths(self, parent: str, commit: str) -> tuple[str, ...]:
        """The repo-relative paths ``commit`` touched, in git's order.

        Every one is allowlisted on the way out, so a caller splitting these into test and
        source files (M1) is working with names it can safely join to a workspace root.
        """
        found = self._git(
            "diff",
            "--name-only",
            "-z",
            _checked_revision(parent),
            _checked_revision(commit),
            "--",
        )
        return tuple(_checked_path(name) for name in _records(found.stdout))

    def diff(self, parent: str, commit: str, paths: Sequence[str]) -> str:
        """The patch from ``parent`` to ``commit``, restricted to ``paths``.

        The restriction is the whole mechanism behind the red-green gate: the same commit is
        asked for its test changes and its source changes separately, and the two halves are
        applied at different moments (SPEC §3).
        """
        return self._git(
            "diff",
            _checked_revision(parent),
            _checked_revision(commit),
            "--",
            *(_checked_path(path) for path in paths),
        ).stdout

    @contextmanager
    def worktree(self, commit: str) -> Iterator[Path]:
        """Check ``commit`` out into a fresh directory under ``worktree_root``, then destroy it.

        The user's clone is never checked out, never made detached, and never left dirty -
        the one honest way to run a mined repository's tests on the host that is also mining
        it. Removal runs in a ``finally``, and is followed by ``git worktree prune`` so the
        administrative entry cannot outlive the directory it named and block the next run.
        """
        self._worktree_root.mkdir(parents=True, exist_ok=True)
        # uuid4 rather than the commit: the same commit may be checked out twice at once (two
        # trials of one task), and `git worktree add` refuses a path that already exists.
        path = self._worktree_root / f"wt-{uuid.uuid4().hex}"
        self._git(
            "worktree",
            "add",
            "--detach",
            str(path),
            _checked_revision(commit),
            timeout_s=_CHECKOUT_TIMEOUT_S,
        )
        try:
            yield path
        finally:
            # Unchecked on purpose: this runs while an exception from the body may be in
            # flight, and losing that exception to a cleanup failure would hide the reason
            # the run stopped. `rmtree` then covers what git declined to remove.
            self._git("worktree", "remove", "--force", str(path), check=False)
            shutil.rmtree(path, ignore_errors=True)
            self._git("worktree", "prune", check=False)

    def apply_patch(self, workspace: Path, patch: str) -> bool:
        """Try to apply ``patch`` inside ``workspace``; report whether it applied.

        ``git apply --check`` first, so a patch that does not apply is an answer (``False``)
        rather than a half-patched tree. That case is expected and counted: a commit whose
        test diff will not apply to its parent is a commit Assay declines to mine.

        Raises:
            GitError: if the patch passed ``--check`` and then failed to apply, which means
                the workspace changed underneath the two calls.
        """
        # Written outside the workspace: `run_command` has no stdin by design, and a scratch
        # file inside a worktree would show up in the very `git diff` that scores the trial.
        handle, name = tempfile.mkstemp(prefix="assay-patch-", suffix=".diff")
        patch_file = Path(name)
        try:
            # Bytes, not text: a patch is exact, and a newline translated on the way to disk
            # is a hunk that no longer matches the file it describes.
            with os.fdopen(handle, "wb") as stream:
                stream.write(patch.encode("utf-8"))
            checked = self._git("apply", "--check", str(patch_file), cwd=workspace, check=False)
            if checked.exit_code != 0:
                return False
            applied = self._git("apply", str(patch_file), cwd=workspace, check=False)
            if applied.exit_code != 0:
                raise GitError(
                    "patch passed `git apply --check` and then failed to apply in "
                    f"{workspace}: {applied.stderr.strip()}"
                )
        finally:
            patch_file.unlink(missing_ok=True)
        return True

    def _git(
        self,
        *arguments: str,
        cwd: Path | None = None,
        timeout_s: int = _QUERY_TIMEOUT_S,
        check: bool = True,
    ) -> CommandResult:
        """Run one git command against this repository, translating a failure to a GitError."""
        argv = ("git", *_CONFIG_FLAGS, *arguments)
        try:
            return run_command(
                argv,
                cwd=cwd if cwd is not None else self._repo,
                timeout_s=timeout_s,
                env=self._env,
                check=check,
            )
        except AssayError as failure:
            raise GitError(str(failure)) from failure


def _records(output: str) -> list[str]:
    """Split NUL-separated git output, dropping the empty tail git leaves behind."""
    return [record for record in output.split("\0") if record]


def _parse_commit(record: str) -> CommitRef | None:
    """Turn one ``git log`` record into a :class:`CommitRef`, or ``None`` if it has no parent.

    A malformed record is a :class:`GitError` - git's own output not having the shape git
    was asked for means the parse is wrong, and mining on a wrong parse is worse than not
    mining. A parentless record is merely the root commit, and is not a candidate.
    """
    fields = record.split(_FIELD_SEPARATOR, 2)
    if len(fields) != 3:
        raise GitError(f"git log record has {len(fields)} fields, expected 3: {record!r}")
    sha, parents, subject = fields
    parent_list = parents.split()
    if len(parent_list) != 1:
        return None
    return CommitRef(
        sha=_checked_revision(sha),
        parent=_checked_revision(parent_list[0]),
        subject=subject,
    )


def _checked_revision(value: str) -> str:
    """Refuse anything that is not an object name before it becomes an argument."""
    if not _REVISION_PATTERN.match(value):
        raise GitError(f"not a git object name: {value!r}")
    return value


def _checked_path(value: str) -> str:
    """Refuse a repository path Assay will not turn into an argument or a filesystem path.

    The rules are the ones that let a name escape the workspace it is supposed to describe,
    and they are the same set :func:`assay.suite.models` pins for a task's ``test_files`` -
    a repo mined on Windows is replayed on Linux, so only repo-relative POSIX names travel.

    Rejection is loud. The alternative - skipping the path and mining the rest of the commit
    - would produce a task whose diff is missing a file, which is a wrong measurement rather
    than a missing one.
    """
    if not value:
        raise GitError("git reported an empty path")
    if "\0" in value:
        raise GitError(f"path contains a NUL byte: {value!r}")
    if "\\" in value:
        raise GitError(f"path is not POSIX-relative (backslash): {value!r}")
    if value.startswith("/"):
        raise GitError(f"path is absolute: {value!r}")
    if re.match(r"^[A-Za-z]:", value):
        raise GitError(f"path carries a drive letter: {value!r}")
    if value.startswith("-"):
        raise GitError(f"path would be read as a command-line option: {value!r}")
    if ".." in value.split("/"):
        raise GitError(f"path escapes the repository (`..` segment): {value!r}")
    return value
