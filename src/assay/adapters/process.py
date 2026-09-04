"""The seam an adapter that drives a command-line tool runs it through.

An agentic tool is a binary somebody else wrote: it is invoked, it edits files, and it exits.
That is a subprocess, and :mod:`assay.host` is the only package allowed to start one - so the
adapter takes this callable and never learns what implements it, in the same shape
``RunnerFactory`` has. The implementation is ``host_tool_process`` in :mod:`assay.cli.main`,
the one module allowed to know both sides.

What the seam is *for* is that every branch of an agentic adapter - the tool that exits
non-zero, the tool that is killed at its budget, the tool that edits nothing - is reachable in
CI on a fake, without the tool being installed on the machine running the tests.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ProcessOutput:
    """What a finished tool invocation produced.

    ``timed_out`` is a field rather than an exception because a tool killed at the trial's
    wall-clock ceiling is a countable outcome of the measurement, not an incident: it is the
    same convention ``TestReport.timed_out`` follows, and the same one that makes
    ``History.apply_patch`` return ``False``. The adapter records it and the trial scores;
    nothing here decides which outcome it becomes.

    ``exit_code`` after a kill is whatever the seam reports for a process that never got to
    choose one, and is read only after ``timed_out`` has been read.
    """

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class ToolProcess(Protocol):
    """Run one command in one directory, under a time budget and an explicit environment.

    ``env`` is required and complete, never merged with the ambient one: the developer's
    shell holds API keys, and a tool under evaluation gets exactly the names the caller chose
    to hand it (plan §7a). ``cwd`` is the adapter's throwaway worktree, never the user's
    clone.

    Deliberately not ``runtime_checkable``: conformance is proved by ``mypy --strict`` where
    the implementation is bound.
    """

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_s: int,
        env: Mapping[str, str],
    ) -> ProcessOutput:
        """Return what the command produced. ``argv`` is already split; there is no shell."""
