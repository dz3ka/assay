"""The values M1's miner passes around, and the one document it reports (SPEC §3).

Two kinds of thing live here, and the difference is deliberate. :class:`TestReport`,
:class:`GateOutcome`, :class:`CommitRef` and :class:`ChangeSplit` are **frozen dataclasses**,
not :class:`assay.core.SchemaModel` subclasses: they are in-process values that are never
serialised, and a ``SchemaModel`` is the base for a *versioned, content-addressed document*.
Making them documents would import schema-stability obligations - ``extra="forbid"`` exists so
a future Assay version's **file** fails loudly - onto internals M2 has to stay free to change.
They are frozen all the same, because a value read by a later gate step must still be the
value the earlier step produced.

:class:`MiningYield` is the other kind. "1,847 commits examined -> 213 valid tasks" is the
number CLAUDE.md requires every report to carry, so it is a reported product and stays a
``SchemaModel``. Every count in it is an ``int``: :func:`assay.core.canonical_json` refuses a
float anywhere in a document (ADR-0008), so a rate computed here rather than at the renderer
would make the yield unhashable. There is deliberately no ``format_line()`` on it either -
rendering belongs at the ``report``/CLI seam, not on a domain model.

Pure: validation and plain values, no I/O. Everything that touches git, a subprocess or the
filesystem is :mod:`assay.host`, behind the protocols in :mod:`assay.mine.protocols`.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self

from pydantic import Field, model_validator

from assay.core import SchemaModel

# One selected test, as the runner names it: ``<repo-relative POSIX path>.py::<test name>``.
#
# The shape is spelled here, in the miner, and *not* narrowed in the suite schema, where
# ``Task.fail_to_pass`` (src/assay/suite/models.py:63) is a plain ``tuple[str, ...]``. Node
# ids are a runner concept and M1 ships exactly one runner; that field is public at v1 and
# CLAUDE.md treats a published schema as API, so narrowing it would be a breaking change made
# on behalf of a runner a future suite may not use. ADR-0012 is the precedent: a constraint is
# spelled twice - or, as here, spelled at the producer and left wide at the boundary - when
# sharing it would couple layers that have different reasons to change. What holds this one
# closed is that the miner is the only thing that mints these ids, and it checks them here.
#
# No whitespace (a selector is one shell-safe argument), no NUL, and no backslash in the path
# half: a suite mined on Windows is replayed on Linux, where a backslash is a filename
# character rather than a separator (the same rule suite/models.py:28 enforces on paths).
_NODE_ID_PATTERN: Final = r"^[^\s\x00\\]+\.py::[^\s\x00]+$"

_NODE_ID: Final = re.compile(_NODE_ID_PATTERN)

type NodeId = str


def is_node_id(value: str) -> bool:
    """Return whether ``value`` is a node id the miner is willing to put in a task.

    The one place ids arrive as untrusted text is the runner's own output, which
    :mod:`assay.host` parses; everything downstream of that check treats them as data.
    """
    # ``fullmatch``, not ``match``: Python's ``$`` also matches before a trailing newline,
    # and a selector carrying one is not a selector.
    return _NODE_ID.fullmatch(value) is not None


class TestStatus(StrEnum):
    """How one selected test ended in one run.

    ``collect_error`` is not an errored test: it is a test that never ran because its module
    would not import. At the parent commit that is the ordinary shape of red - a new test
    importing something the fix adds - so the gate counts it as a failure rather than as a
    harness problem.
    """

    PASSED = "passed"
    FAILED = "failed"
    ERRORED = "errored"
    COLLECT_ERROR = "collect_error"


class GateRejection(StrEnum):
    """Why a candidate commit did not become a task.

    The set is closed at eight and every discard is counted under one of them, because yield
    accounting is a partition of what was examined: a ninth reason introduced without a place
    in the accounting would quietly lose commits from the denominator, and the denominator is
    the honest half of the result (CLAUDE.md, "report yield, not just totals").

    The first four are decided before anything runs - by :mod:`assay.mine.gate`'s caller, on
    the commit and its diff. The last four are the verdicts of the red->green gate itself.
    """

    MERGE_COMMIT = "merge_commit"
    NO_TEST_CHANGES = "no_test_changes"
    NO_SOURCE_CHANGES = "no_source_changes"
    PATCH_DID_NOT_APPLY = "patch_did_not_apply"
    ALREADY_GREEN = "already_green"
    STILL_RED = "still_red"
    UNSTABLE_GREEN = "unstable_green"
    RUN_TIMED_OUT = "run_timed_out"


@dataclass(frozen=True)
class TestReport:
    """What one test run observed - the only evidence the gate is allowed to decide on.

    ``uncollectable`` names files (repo-relative POSIX) the runner could not collect at all,
    which produce no node ids and so cannot appear in ``statuses``. ``exit_code`` is the
    runner's own, kept raw rather than interpreted here: the gate reads it for the one case
    where the exit code says something the statuses cannot (see :func:`assay.mine.decide_gate`).
    """

    statuses: Mapping[NodeId, TestStatus]
    uncollectable: tuple[str, ...]
    exit_code: int
    timed_out: bool


@dataclass(frozen=True)
class GateOutcome:
    """The gate's verdict on one candidate: a rejection, or the two sets a task is scored on.

    Exactly one side is populated. ``rejection is None`` means accepted, and then
    ``fail_to_pass`` is non-empty - a task with nothing to turn from red to green has no gate
    and could not be scored (``Task.fail_to_pass`` is ``min_length=1`` for the same reason).
    """

    rejection: GateRejection | None
    fail_to_pass: tuple[NodeId, ...]
    pass_to_pass: tuple[NodeId, ...]


@dataclass(frozen=True)
class CommitRef:
    """One commit worth examining, and the parent the task would be checked out at.

    Single-parent by construction: the walk asks git for ``--no-merges``, so ``parent`` is a
    sha rather than a list, and a merge commit never reaches the gate as a candidate.
    """

    sha: str
    parent: str
    subject: str


@dataclass(frozen=True)
class ChangeSplit:
    """A commit's changed paths, divided into the test patch and the ground-truth patch.

    The division is total - every changed path is in exactly one half - because the two
    patches are cut from these tuples, and a path in neither would be a change that
    disappears from both.
    """

    test_files: tuple[str, ...]
    source_files: tuple[str, ...]


class MiningYield(SchemaModel):
    """What a mining run examined, what it kept, and why it discarded the rest.

    CLAUDE.md forbids reporting the task count alone, so the denominator travels with the
    numerator in one value rather than being reassembled by whoever prints it.
    """

    commits_examined: int = Field(ge=0)
    candidates: int = Field(ge=0)
    accepted: int = Field(ge=0)
    # Counts per reason, ints only: a float has no stable canonical encoding (ADR-0008), so
    # any rate a reader wants is computed at the renderer, from these.
    rejected: Mapping[GateRejection, int]

    @model_validator(mode="after")
    def _check_counts_nest(self) -> Self:
        """Refuse a yield line whose numerator exceeds the denominator it came from.

        Every accepted task was a candidate and every candidate was an examined commit, so
        this is arithmetic rather than policy - and it is the one arithmetic that would
        overstate the result, which is the direction this project cannot afford to be wrong in.
        """
        if self.candidates > self.commits_examined:
            raise ValueError(
                f"candidates ({self.candidates}) exceeds commits examined ({self.commits_examined})"
            )
        if self.accepted > self.candidates:
            raise ValueError(f"accepted ({self.accepted}) exceeds candidates ({self.candidates})")
        return self
