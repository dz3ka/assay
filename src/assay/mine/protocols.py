"""The two seams the miner reaches the outside world through (SPEC §6, CLAUDE.md).

Mining is a pure function over explicit inputs; git and pytest are not. These protocols are
the boundary between the two: :mod:`assay.mine` names what it needs, :mod:`assay.host`
implements it with subprocesses and temporary worktrees, and the rule in
:mod:`assay.mine.gate` never learns which. That is what makes the gate fixture-testable, and
it is why nothing in this package imports ``subprocess``, ``shutil`` or ``git``.

Neither is ``runtime_checkable``, matching :class:`assay.adapters.Adapter`. An
``isinstance`` check against a runtime-checkable protocol only asks whether the attribute
names exist - never whether the signatures agree - so conformance is proved statically, by
``mypy --strict``, at the point of assignment.
"""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from assay.mine.models import CommitRef, TestReport


class History(Protocol):
    """Read-only access to one repository's git history and working states."""

    def repo_url(self) -> str:
        """The origin the mined tasks cite. Never emitted unredacted; the report owns that."""

    def commits(self, *, limit: int | None) -> Iterator[CommitRef]:
        """Walk candidate commits, newest first, ``--no-merges`` so each has one parent.

        An iterator rather than a sequence: a large repository's history is walked until
        enough tasks are accepted, and the walk should not have to finish first.
        """

    def changed_paths(self, parent: str, commit: str) -> tuple[str, ...]:
        """The repo-relative POSIX paths ``commit`` changed against ``parent``."""

    def diff(self, parent: str, commit: str, paths: Sequence[str]) -> str:
        """The patch text for ``paths`` only - one half of the split, never the whole commit."""

    def worktree(self, commit: str) -> AbstractContextManager[Path]:
        """Check ``commit`` out into a disposable workspace, removed when the context exits.

        A context manager because the gate runs several times per candidate and a leaked
        worktree costs a checkout of the repository under evaluation each time.
        """

    def apply_patch(self, workspace: Path, patch: str) -> bool:
        """Apply ``patch`` in ``workspace``; return False if it did not apply cleanly.

        False rather than an exception: a patch that will not apply to its own parent is an
        ordinary, countable outcome (``GateRejection.PATCH_DID_NOT_APPLY``), not a failure of
        the miner.
        """


class TestRunner(Protocol):
    """Running a repository's own test suite over a selection, under a wall-clock ceiling."""

    def run(self, workspace: Path, selectors: Sequence[str], *, timeout_s: int) -> TestReport:
        """Run ``selectors`` in ``workspace`` and report what happened.

        A run that hits ``timeout_s`` returns a report with ``timed_out`` set rather than
        raising: a candidate that cannot be measured in time is discarded and counted, and
        the miner keeps walking.
        """
