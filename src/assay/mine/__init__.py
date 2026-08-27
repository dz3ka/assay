"""Mining tasks out of a repository's own git history, and the gate that validates them.

Import these names from ``assay.mine`` rather than from the submodules; the split between
``models`` (the values and the reported yield), ``protocols`` (the git and test-runner seams),
``candidates`` (one commit into a candidate task) and ``gate`` (the red->green rule) is an
implementation detail, this surface is not.

Everything here is pure. Git, subprocesses, worktrees and the filesystem live in
:mod:`assay.host`, which implements :class:`History` and :class:`TestRunner`, so the rule that
decides whether a commit is a task can be exercised on values alone (CLAUDE.md).

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

from assay.mine.candidates import build_prompt, is_test_path, mint_task_id, split_changes
from assay.mine.gate import GREEN_CONFIRMATION_RUNS, decide_gate
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
from assay.mine.protocols import History, TestRunner

__all__ = [
    "GREEN_CONFIRMATION_RUNS",
    "ChangeSplit",
    "CommitRef",
    "GateOutcome",
    "GateRejection",
    "History",
    "MiningYield",
    "NodeId",
    "TestReport",
    "TestRunner",
    "TestStatus",
    "build_prompt",
    "decide_gate",
    "is_node_id",
    "is_test_path",
    "mint_task_id",
    "split_changes",
]
