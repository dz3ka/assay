"""The adapter that does nothing at all - the floor every real result is read against.

An empty diff cannot fix a task, so a run of this adapter has exactly one correct answer: a
score of zero. A harness that gives it anything else is scoring something other than the tests
it claims to be running. Paired with :mod:`assay.adapters.ground_truth` it brackets every real
result (SPEC §9), and a tool that cannot beat this floor has told you something.

Producing nothing is success here, not failure: ``error`` stays ``None``, because "the tool
solved nothing" and "the harness broke" are different findings and a report must not merge
them (:class:`assay.results.Outcome`).
"""

from decimal import Decimal
from pathlib import Path
from time import monotonic_ns

from assay.results import Attempt, Budget
from assay.suite import Task

# The twin of the constants in :mod:`assay.adapters.ground_truth`, copied rather than shared:
# neither adapter owns the other's internals, and the third adapter that needs them is the one
# that should lift them somewhere common. The M0 pair is deliberately two files of no shared
# machinery, so that neither bracket can be broken by a change made for the other.
_NS_PER_MS = 1_000_000
_NO_COST = Decimal("0.000000")
_FIRST_TRIAL = 0

# Not a placeholder: an empty diff is this adapter's whole output, and the value
# :class:`assay.results.Attempt` documents as the floor.
_NO_DIFF = ""


class NullAdapter:
    """Returns an empty diff, having done nothing to the workspace or to a model."""

    name: str = "null"
    version: str = "0.1.0"

    def run(self, task: Task, workspace: Path, budget: Budget) -> Attempt:
        """Workspace is a repo checked out at the task's base state, tests already
        failing. Return the diff produced, plus token and latency accounting.

        Neither ``workspace`` nor ``budget`` is touched: there is nothing to write and
        nothing to cap. Only ``task`` is read, and only to say which task this attempt
        belongs to - a result is an attribution claim before it is a measurement (SPEC §5.5).
        """
        started_ns = monotonic_ns()
        return Attempt(
            schema_version=1,
            adapter_name=self.name,
            adapter_version=self.version,
            task_id=task.task_id,
            trial_index=_FIRST_TRIAL,
            diff=_NO_DIFF,
            input_tokens=0,
            output_tokens=0,
            # Still measured. The floor of a report states what it cost like any other row.
            wall_clock_ms=(monotonic_ns() - started_ns) // _NS_PER_MS,
            tool_calls=0,
            retries=0,
            cost_usd=_NO_COST,
            error=None,
        )
