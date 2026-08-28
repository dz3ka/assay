"""Mining tasks out of a repository's own git history, and the gate that validates them.

Import these names from ``assay.mine`` rather than from the submodules; the split between
``models`` (the values and the reported yield), ``protocols`` (the git and test-runner seams),
``candidates`` (one commit into a candidate task), ``gate`` (the red->green rule) and
``pipeline`` (the walk that gathers the rule's evidence) is an implementation detail, this
surface is not.

Nothing here imports git, uv, pytest or ``subprocess``. Those live in :mod:`assay.host`, which
implements :class:`History` and :class:`TestRunner`, so the rule that decides whether a commit
is a task can be exercised on values alone (CLAUDE.md). ``models``, ``candidates`` and ``gate``
are pure in the stronger sense of doing no I/O at all; ``pipeline`` is the one module that
drives the seams, and it is the package's I/O half for that reason.

Two deliberate deviations, so neither reads as an oversight:

**`mine` and `validate` are one package, not the two SPEC §6's tree implies.** `validate`
re-runs the byte-identical gate over a suite that already exists; splitting it out would mean
a third module shared by both - this package plus a layer of indirection - to keep the two
copies of the rule from drifting. One package, one rule, two entry points.

**The two commands exit differently on an empty result, on purpose.** `assay mine` finishing
with a yield of zero exits **0**: a repository whose history holds no red->green commit is a
finding about that repository, honestly reported, not a failure of the tool. `assay validate`
finding any task invalid exits **1**: there the suite asserts something untrue, and a build
that goes on believing it is the failure this project exists to prevent.
"""

from assay.mine.candidates import (
    build_prompt,
    is_test_path,
    mint_task_id,
    pytest_selectors,
    split_changes,
)
from assay.mine.gate import GREEN_CONFIRMATION_RUNS, decide_gate, revalidates
from assay.mine.models import (
    ChangeSplit,
    CommitRef,
    GateOutcome,
    GateRejection,
    MiningYield,
    NodeId,
    TestReport,
    TestStatus,
    is_node_id,
)
from assay.mine.pipeline import (
    MinedCommit,
    mine_suite,
    revalidate_suite,
    run_gate,
    tally_yield,
)
from assay.mine.protocols import History, RunnerFactory, TestRunner

__all__ = [
    "GREEN_CONFIRMATION_RUNS",
    "ChangeSplit",
    "CommitRef",
    "GateOutcome",
    "GateRejection",
    "History",
    "MinedCommit",
    "MiningYield",
    "NodeId",
    "RunnerFactory",
    "TestReport",
    "TestRunner",
    "TestStatus",
    "build_prompt",
    "decide_gate",
    "is_node_id",
    "is_test_path",
    "mine_suite",
    "mint_task_id",
    "pytest_selectors",
    "revalidate_suite",
    "revalidates",
    "run_gate",
    "split_changes",
    "tally_yield",
]
