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

    The set is closed at seven and every discard is counted under one of them, because yield
    accounting is a partition of what was examined: an eighth reason introduced without a
    place in the accounting would quietly lose commits from the denominator, and the
    denominator is the honest half of the result (CLAUDE.md, "report yield, not just totals").

    "Examined" means the walk's output, not the commit range. :meth:`History.commits` yields
    single-parent commits only - ``GitHistory.commits`` asks git for ``--no-merges``, and a
    record that arrives without exactly one parent is dropped - so a merge and the root commit
    are never examined at all. They sit **outside** the accounting rather than inside it as a
    reason, which is why there is deliberately no ``merge_commit`` member: nothing could ever
    be counted under it, and a permanent ``merge_commit: 0`` in every reported yield reads as
    "merges were examined and none was rejected" when the truth is that none was looked at.
    Naming the population is the honest fix; widening the reason set is not (ADR-0015).

    The first three are decided before anything runs - by :mod:`assay.mine.gate`'s caller, on
    the commit and its diff. The last four are the verdicts of the red->green gate itself.
    """

    NO_TEST_CHANGES = "no_test_changes"
    NO_SOURCE_CHANGES = "no_source_changes"
    PATCH_DID_NOT_APPLY = "patch_did_not_apply"
    ALREADY_GREEN = "already_green"
    STILL_RED = "still_red"
    UNSTABLE_GREEN = "unstable_green"
    RUN_TIMED_OUT = "run_timed_out"


# The rejections settled before :func:`assay.mine.decide_gate` is ever reached - on the
# commit's own diff, or on a patch that would not apply. A commit rejected for one of these is
# examined but is not a candidate, which is the difference between the two denominators a
# yield reports.
#
# It lives in this module because :class:`MiningYield`'s validator is what needs it and
# ``models`` cannot import ``pipeline`` - that is import direction, not deduplication.
# ``tests/fixture_repo.py`` keeps its own independent second spelling of the same split on
# purpose (ADR-0012): an oracle that imports its answer from the code under test proves
# nothing, so that copy stays where it is.
PRE_GATE_REJECTIONS: Final[frozenset[GateRejection]] = frozenset(
    {
        GateRejection.NO_TEST_CHANGES,
        GateRejection.NO_SOURCE_CHANGES,
        GateRejection.PATCH_DID_NOT_APPLY,
    }
)

# The gate's own verdicts: the complement, never a second hand-written set. Two hand-written
# frozensets over one enum can drift into something that is not a partition, and a member
# added to :class:`GateRejection` later lands on exactly one side of this one by construction.
GATE_VERDICTS: Final[frozenset[GateRejection]] = frozenset(GateRejection) - PRE_GATE_REJECTIONS


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
    sha rather than a list. A merge is not yielded by the walk at all, so it is never
    examined, never a candidate, and never counted as a rejection (ADR-0015).
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

    # The denominator is the **single-parent commits** the walk yielded, not every commit
    # in the range: a merge and the root are outside this accounting entirely (ADR-0015). The
    # rendered yield line says so in words, because a bare "commits examined" would be read as
    # the whole history.
    commits_examined: int = Field(ge=0)
    candidates: int = Field(ge=0)
    accepted: int = Field(ge=0)
    # Counts per reason, ints only: a float has no stable canonical encoding (ADR-0008), so
    # any rate a reader wants is computed at the renderer, from these.
    rejected: Mapping[GateRejection, int]
    # Commits the walk yielded whose workspace could not be given an environment its tests
    # could run in (:data:`assay.mine.protocols.RunnerFactory` returned ``None``). They are
    # examined - the walk did yield them - and they are not candidates, because the gate never
    # spoke about them. Counted here, outside the seven reasons, for the reason ADR-0015 gives
    # for merges: name the population, do not widen the reason set.
    #
    # Rejected alternative: an eighth ``GateRejection.ENVIRONMENT_FAILED``. A rejection reason
    # has to have a walked fixture witness (``tests/mine/test_fixture_repo.py`` asserts every
    # member is reached by a real commit), and no stub runner factory can honestly fabricate a
    # witness for a real ``uv pip install`` failure - the only true witness would put a
    # network-dependent install into CI.
    #
    # Defaulted to zero so the fixture oracle, which constructs a yield without this field,
    # still describes the same partition - and so that a yield serialised before the field
    # existed would too, once anything in the pipeline parses one back.
    unprovisioned: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_partition(self) -> Self:
        """Refuse a yield that is not the partition of examined commits it claims to be.

        Four clauses, because the counting contract is four claims. Every reason is present,
        zeros included, so "never fired" and "not looked for" cannot be the same document
        (ADR-0015). No count is negative. Every examined commit is accepted, rejected for one
        reason, or unprovisioned - exactly one. And every candidate is a commit the gate spoke
        about: accepted, or rejected for one of :data:`GATE_VERDICTS`.

        This lives here rather than only in :func:`assay.mine.tally_yield` because a yield is
        meant to be read back from a file and not only produced - no M1 path parses one yet - and
        a rule that only the producer enforces is the "escape once in a shared helper every
        renderer calls" that ADR-0011 rejected.

        The two nesting inequalities this replaced (``candidates <= commits_examined``,
        ``accepted <= candidates``) are dropped as implied by clauses 3 and 4 - **but only
        because clause 2 is here**, and in that order. ``Field(ge=0)`` constrains the scalars
        and says nothing about ``rejected``'s values, so a negative count is exactly what would
        balance both equalities while overstating ``accepted``.
        """
        if set(self.rejected) != set(GateRejection):
            missing = sorted(reason.value for reason in set(GateRejection) - set(self.rejected))
            raise ValueError(f"rejected must name every reason; it is missing {missing}")
        negative = sorted(reason.value for reason, count in self.rejected.items() if count < 0)
        if negative:
            raise ValueError(f"rejected holds a negative count for {negative}")

        discarded = sum(self.rejected.values())
        if self.accepted + discarded + self.unprovisioned != self.commits_examined:
            raise ValueError(
                f"accepted ({self.accepted}) + rejected ({discarded}) + unprovisioned "
                f"({self.unprovisioned}) does not partition commits examined "
                f"({self.commits_examined})"
            )
        judged = sum(self.rejected[reason] for reason in GATE_VERDICTS)
        if self.accepted + judged != self.candidates:
            raise ValueError(
                f"accepted ({self.accepted}) + gate verdicts ({judged}) does not partition "
                f"candidates ({self.candidates})"
            )
        return self
