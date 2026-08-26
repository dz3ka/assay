"""The one interface every tool under evaluation is driven through, copied from SPEC §6.

It is this small on purpose. Each member is a member every future adapter has to implement -
an agentic CLI, an editor in a batch mode, a raw model API - and each one narrows what can be
made to fit. There is no ``close()`` and no setup hook: an adapter that needs a lifecycle owns
it inside ``run``, where the wall clock it costs is already being measured.

``name`` and ``version`` are two fields rather than one string because a tool that changed
between two runs is a different tool, and a report that cannot say which one it measured is
not reproducible (:class:`assay.results.Attempt`).

Pure interface: no implementation lives here. The M0 adapters that satisfy it are
:mod:`assay.adapters.ground_truth` and :mod:`assay.adapters.null`.
"""

from pathlib import Path
from typing import Protocol

from assay.results import Attempt, Budget
from assay.suite import Task


class Adapter(Protocol):
    name: str
    version: str

    def run(self, task: Task, workspace: Path, budget: Budget) -> Attempt:
        """Workspace is a repo checked out at the task's base state, tests already
        failing. Return the diff produced, plus token and latency accounting."""
