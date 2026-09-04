"""The adapter that replays a task's known-good diff - the oracle, not a tool under test.

It exists to make the harness's own scoring falsifiable. Every mined task carries a diff that
provably turns its tests from red to green (SPEC §3), so an end-to-end run of this adapter has
exactly one correct answer: a perfect score. Anything less is a bug in the miner, the sandbox
or the scorer, and without this adapter that bug would surface as a finding about somebody's
tool instead. Paired with :mod:`assay.adapters.null` it brackets every real result (SPEC §9).

It is emphatically **not** a real adapter: it calls no model, reads nothing, and knows the
answer before it starts. It must never appear in a report as a tool that was evaluated.
"""

from decimal import Decimal
from pathlib import Path
from time import monotonic_ns

from assay.results import Attempt, Budget
from assay.suite import Task

_NS_PER_MS = 1_000_000

# Written to six decimal places because the schema refuses any other spelling of an amount
# (:mod:`assay.results.models`); ``Decimal(0)`` is the same number and a different document.
_NO_COST = Decimal("0.000000")


class GroundTruthAdapter:
    """Returns the task's ground-truth patch, unmodified, as its attempt."""

    name: str = "ground-truth"
    # The harness's own version: this adapter ships with Assay rather than being a tool that
    # has one of its own, so what a result attributes it to is the build that produced it.
    version: str = "0.1.0"

    def run(self, task: Task, workspace: Path, budget: Budget, *, trial_index: int) -> Attempt:
        """Workspace is a repo checked out at the task's base state, tests already
        failing. Return the diff produced, plus token and latency accounting.

        ``workspace`` is read no more than it is written: applying the diff is the runner's
        job in M2, inside a container (SPEC §5.2), and M0 runs on the host. ``budget`` is
        unused for the reason the accounting below is zero - there is no work here to cap.

        ``trial_index`` is recorded and nothing else: this adapter answers every trial of a
        task with the same diff, on purpose, so the trial number is the only thing that tells
        its n attempts apart (ADR-0033).
        """
        started_ns = monotonic_ns()
        # The entire operation. That it is a lookup rather than a search is the point of it.
        diff = task.ground_truth_patch
        return Attempt(
            schema_version=1,
            adapter_name=self.name,
            adapter_version=self.version,
            task_id=task.task_id,
            trial_index=trial_index,
            diff=diff,
            input_tokens=0,
            output_tokens=0,
            # Measured, never declared: a latency a report prints is a latency something
            # timed (CLAUDE.md), even when the thing timed is this cheap. Floor division,
            # so sub-millisecond work reports the 0 ms it took rather than rounding up.
            wall_clock_ms=(monotonic_ns() - started_ns) // _NS_PER_MS,
            tool_calls=0,
            retries=0,
            cost_usd=_NO_COST,
            error=None,
        )
