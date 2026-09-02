"""Running a mined repository's own pytest suite, and reading what it actually did.

This is the ``TestRunner`` half of the seam in :mod:`assay.mine.protocols`: two bounded
subprocesses per run, and a :class:`~assay.mine.models.TestReport` of plain values that the
gate decides on without ever learning that pytest exists.

Two commands, because one cannot answer both questions:

1. ``pytest --collect-only -q`` enumerates the node ids the selection actually resolves to.
   Parametrised cases are the reason - ``TestThing::test_p`` is two tests and the report is
   keyed per test - and it is how a later milestone enumerates ``fail_to_pass`` candidates
   from a test *file* rather than from a list of ids.
2. ``pytest --junit-xml=<file>`` produces the statuses. Turning what those two commands
   printed and wrote into a report is :mod:`assay.host.junit`, which is pure and records the
   junit shapes it was measured against. It lives apart from this module because M2's sandbox
   scorer reads a report produced by a run it did not start: one spelling of the rules, one
   verdict on a given run, whichever side of the sandbox wall the run happened on.

An earlier design injected a pytest plugin to observe statuses in-process. It was cut after
measurement: the junit XML distinguishes every shape the gate can act on, and a plugin would
have to be installed into a mined repository's environment to buy nothing.

``-p no:cacheprovider`` is on every invocation: a ``.pytest_cache`` written inside a worktree
would be a directory Assay created in a tree it is about to score.
"""

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from time import monotonic
from types import MappingProxyType
from typing import Final

from assay.core import AssayError
from assay.host.junit import build_test_report
from assay.host.process import CommandResult, CommandTimeoutError, minimal_env, run_command
from assay.mine.models import TestReport

# Flags on every invocation. ``-p no:cacheprovider`` keeps ``.pytest_cache`` out of the
# worktree; ``-q`` keeps the collected node ids one per line, which is the format
# :func:`assay.host.junit.build_test_report` reads them back out of.
_ALWAYS: Final = ("-p", "no:cacheprovider", "-q")

# The exit code reported when a run was killed at its budget. A killed process has no exit
# status worth passing on, and the gate reads ``timed_out`` before it reads this field; the
# value is negative so it can never be mistaken for one of pytest's own, which are 0 to 5.
_KILLED_EXIT_CODE: Final = -1


class SelectorError(AssayError):
    """Assay refused a test selector rather than letting it decide what pytest runs.

    An id that is empty, or one that would reach the argv as a command-line option. Both would
    change the command rather than the selection - a smaller suite, or a different one - and
    the gate would then be deciding on a run nobody asked for, so the value is refused loudly
    instead of dropped.

    An :class:`~assay.core.AssayError` rather than the ``ValueError`` this refusal used to be,
    for the reason :mod:`assay.sandbox.errors` gives about the identical refusal on the other
    side of the wall: the base class is how :mod:`assay.cli` ends a command on one sentence
    rather than a traceback, and a bare ``ValueError`` would pass straight through the handler
    that does it. What it is *not* is a per-row catch on the mining path - the one refusal
    recorded rather than raised is :func:`assay.host.provision_venv`'s, caught at the host seam
    in ``assay.cli.host_runner_for`` and counted ``unprovisioned`` - and a walk does not reach
    this refusal at all, because :func:`assay.mine.pytest_selectors` decides a selector's
    usability on the task's own data before a runner is built (ADR-0029).
    :func:`assay.score.run_trial`, which selects by a task's recorded node ids, is the one
    caller where this refusal still ends the run, and ADR-0029 names that residue deliberate.

    Its own class in the module that raises it, which is the placement rule in
    :mod:`assay.core.errors`, and the same rule that gave ``git`` a :class:`GitError` and
    ``venv`` an :class:`EnvironmentSetupError`. Not shared with the sandbox runner's
    :class:`assay.sandbox.SandboxError`, which refuses the same input on the far side: a
    common class would have to live in ``core`` or make one package import the other, and what
    the two refusals owe each other is the base, which they now have.
    """


class PytestHostRunner:
    """Runs pytest in a workspace, with the interpreter that workspace was provisioned with.

    Args:
        python: The environment's interpreter, from :func:`assay.host.provision_venv`. Tests
            run as ``python -m pytest`` rather than as a ``pytest`` found on PATH, so the
            suite that runs is the one installed beside the repository's own dependencies.

    Satisfies :class:`assay.mine.protocols.TestRunner` structurally, the way
    :class:`assay.host.GitHistory` satisfies ``History``: no base class, conformance proved by
    ``mypy --strict`` at the one place a ``TestRunner`` is annotated.
    """

    def __init__(self, python: Path) -> None:
        self._python = python
        # Built once, and never from ``os.environ``: a mined repository's tests execute as the
        # invoking user, and the developer's shell holds model API keys (SPEC §5.2).
        self._env: Final = minimal_env()

    def run(self, workspace: Path, selectors: Sequence[str], *, timeout_s: int) -> TestReport:
        """Run ``selectors`` in ``workspace`` and report what happened.

        The budget covers both invocations: the collection pass is charged against it and the
        measuring pass gets what is left, so ``timeout_s`` is a ceiling on the run rather than
        an allowance that can be paid twice. A run that hits it returns a report with
        ``timed_out`` set and no statuses, per the protocol - a candidate that cannot be
        measured in time is discarded and counted, and the miner keeps walking.

        Raises:
            SelectorError: if a selector is empty or could be read as a command-line option.
                Every other hostile shape is data the report carries; this one would change
                the command that runs.
        """
        checked = tuple(_checked_selector(selector) for selector in selectors)
        deadline = monotonic() + timeout_s
        # Outside the workspace, like ``git apply``'s patch file: a report written into the
        # worktree would be a file Assay added to a tree it is about to score.
        handle, name = tempfile.mkstemp(prefix="assay-junit-", suffix=".xml")
        os.close(handle)
        junit = Path(name)
        try:
            try:
                collected = self._pytest(
                    workspace, "--collect-only", *checked, timeout_s=_remaining(deadline)
                )
                measured = self._pytest(
                    workspace, f"--junit-xml={junit}", *checked, timeout_s=_remaining(deadline)
                )
            except CommandTimeoutError:
                return TestReport(
                    statuses=MappingProxyType({}),
                    uncollectable=(),
                    exit_code=_KILLED_EXIT_CODE,
                    timed_out=True,
                )
            junit_xml = _junit_text(junit)
        finally:
            junit.unlink(missing_ok=True)

        return build_test_report(
            collected_stdout=collected.stdout,
            junit_xml=junit_xml,
            selectors=checked,
            exit_code=measured.exit_code,
        )

    def _pytest(self, workspace: Path, *arguments: str, timeout_s: int) -> CommandResult:
        """One pytest invocation. Never ``check=True``: pytest's exit code is the answer."""
        return run_command(
            (str(self._python), "-m", "pytest", *_ALWAYS, *arguments),
            cwd=workspace,
            timeout_s=timeout_s,
            env=self._env,
        )


def _checked_selector(value: str) -> str:
    """Refuse a selector that would be read as an option rather than as a test to run.

    Node ids reach this module from a mined repository's own file names by way of
    :class:`assay.host.GitHistory`, which refuses a leading dash on a *path*; an id assembled
    anywhere else gets the same check here, because this is where it becomes an argv entry.
    Loud rather than filtered: dropping a selector silently would run a smaller suite than the
    gate believes it ran.
    """
    if not value:
        raise SelectorError("a test selector is empty")
    if value.startswith("-"):
        raise SelectorError(f"selector would be read as a command-line option: {value!r}")
    return value


def _junit_text(path: Path) -> str | None:
    """The report pytest wrote, or ``None`` when there is nothing readable to hand on.

    A missing or unreadable file is no evidence rather than an error: pytest writes the report
    as it exits, and a mined test that takes the process down with it (``os._exit``, a
    segfault) leaves nothing behind. :func:`assay.host.junit.build_test_report` reads ``None``
    and unparsable XML the same way, so the two halves of "there is no report" stay one rule.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _remaining(deadline: float) -> int:
    """Seconds left before ``deadline``, never below one - a zero budget kills on the spot."""
    return max(1, int(deadline - monotonic()))
