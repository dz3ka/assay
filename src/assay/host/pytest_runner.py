"""Running a mined repository's own pytest suite, and reading what it actually did.

This is the ``TestRunner`` half of the seam in :mod:`assay.mine.protocols`: two bounded
subprocesses per run, and a :class:`~assay.mine.models.TestReport` of plain values that the
gate decides on without ever learning that pytest exists.

Two commands, because one cannot answer both questions:

1. ``pytest --collect-only -q`` enumerates the node ids the selection actually resolves to.
   Parametrised cases are the reason - ``TestThing::test_p`` is two tests and the report is
   keyed per test - and it is how a later milestone enumerates ``fail_to_pass`` candidates
   from a test *file* rather than from a list of ids.
2. ``pytest --junit-xml=<file>`` produces the statuses. The XML is keyed by
   ``(classname, name)``, not by node id, so this module maps each *known* id forward into
   that pair. Forward, never backward: ``classname="pkg.test_deep.TestThing"`` cannot be
   turned back into a path and a class without guessing which dots were slashes, and Assay
   owns the id set, so the direction that needs no guess is the one available.

An earlier design injected a pytest plugin to observe statuses in-process. It was cut after
measurement: the junit XML distinguishes every shape the gate can act on, and a plugin would
have to be installed into a mined repository's environment to buy nothing.

**Measured against pytest 9.1.1 on 2026-08-27** - the shapes this module is written to, and
the ones the gate's rules are calibrated against:

* Passed: ``<testcase classname="pkg.sub.test_deep" name="test_plain" />``, self-closing.
  A class nests into the classname: ``classname="pkg.sub.test_deep.TestThing"``,
  ``name="test_p[1]"``. Module naming is rootdir-relative and dotted whether or not the
  directories hold an ``__init__.py``.
* Failed: a ``<failure>`` child. Errored (a setup or teardown that raised): an ``<error>``
  child. Skipped/xfailed: a ``<skipped>`` child, which this module drops - a test that did
  not run is not evidence either way, and there is deliberately no ``TestStatus`` for it.
* Collection error: ``<testsuite errors="1" tests="1">`` holding one
  ``<testcase classname="" name="pkg.sub.test_bad"><error message="collection failure">``.
  The empty classname is the discriminator. **One unimportable module aborts the entire
  run** - the sibling tests never execute - so this arrives as a whole-run verdict rather
  than as a per-test one.
* Nothing to run: a self-closing ``<testsuite errors="0" failures="0" tests="0" />``. Two
  distinct exit codes produce it, and telling them apart is the gate's business, not this
  module's: **exit 4** when a selected node id does not resolve (measured: a valid sibling in
  the same argv is *not* run - the whole selection is refused), and **exit 5** when the
  selection resolves to nothing collectable at all (an empty directory, a test file holding
  no tests, a ``-k`` that matches nothing). ``exit_code`` therefore travels raw in the
  report; :mod:`assay.mine.gate` reads 4 as evidence of red, and 5 is not yet interpreted.

``-p no:cacheprovider`` is on every invocation: a ``.pytest_cache`` written inside a worktree
would be a directory Assay created in a tree it is about to score.
"""

import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import monotonic
from types import MappingProxyType
from typing import Final
from xml.etree import ElementTree

from assay.host.process import CommandResult, CommandTimeoutError, minimal_env, run_command
from assay.mine.models import NodeId, TestReport, TestStatus, is_node_id

# Flags on every invocation. ``-p no:cacheprovider`` keeps ``.pytest_cache`` out of the
# worktree; ``-q`` keeps the collected node ids one per line, which is the format
# :func:`_collected_ids` reads.
_ALWAYS: Final = ("-p", "no:cacheprovider", "-q")

# The exit code reported when a run was killed at its budget. A killed process has no exit
# status worth passing on, and the gate reads ``timed_out`` before it reads this field; the
# value is negative so it can never be mistaken for one of pytest's own, which are 0 to 5.
_KILLED_EXIT_CODE: Final = -1

# The junit child element a status is read from. ``skipped`` is absent on purpose - see the
# module docstring - and a testcase with no child element at all is a pass.
_STATUS_BY_ELEMENT: Final = MappingProxyType(
    {"failure": TestStatus.FAILED, "error": TestStatus.ERRORED}
)


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
            ValueError: if a selector is empty or could be read as a command-line option.
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
            outcomes, uncollectable = _read_junit(junit)
        finally:
            junit.unlink(missing_ok=True)

        known = _collected_ids(collected.stdout) | {s for s in checked if is_node_id(s)}
        return TestReport(
            statuses=_statuses(known, outcomes, uncollectable),
            uncollectable=uncollectable,
            exit_code=measured.exit_code,
            timed_out=False,
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
        raise ValueError("a test selector is empty")
    if value.startswith("-"):
        raise ValueError(f"selector would be read as a command-line option: {value!r}")
    return value


def _collected_ids(output: str) -> set[NodeId]:
    """The node ids ``--collect-only -q`` printed, and nothing else that it printed.

    ``-q`` prints one id per line and then a summary, and a collection error adds a traceback
    - so the filter is :func:`assay.mine.models.is_node_id`, the miner's own definition of an
    id it is willing to put in a task, rather than a line count. Measured: collection still
    prints the ids it *did* resolve when the same argv also names one it could not (exit 4),
    so this set is trustworthy even on a run that then refused to execute anything.
    """
    return {line for line in (raw.strip() for raw in output.splitlines()) if is_node_id(line)}


def _read_junit(path: Path) -> tuple[Mapping[tuple[str, str], TestStatus], tuple[str, ...]]:
    """Read one junit report into ``(status by (classname, name), uncollectable files)``.

    A missing or truncated file is read as no evidence rather than raised on: pytest writes
    the report as it exits, and a mined test that takes the process down with it (``os._exit``,
    a segfault) leaves nothing to parse. Such a run reports no statuses and a non-zero exit
    code, which every rule in :mod:`assay.mine.gate` discards - the conservative direction.
    """
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return {}, ()

    outcomes: dict[tuple[str, str], TestStatus] = {}
    uncollectable: set[str] = set()
    for case in root.iter("testcase"):
        name = case.get("name", "")
        classname = case.get("classname", "")
        children = {child.tag for child in case}
        if "error" in children and not classname:
            # An empty classname is pytest's shape for "this module never imported", and its
            # ``name`` is the dotted module path rather than a file name.
            uncollectable.add(_module_path(name))
        elif "skipped" not in children:
            outcomes[(classname, name)] = next(
                (status for tag, status in _STATUS_BY_ELEMENT.items() if tag in children),
                TestStatus.PASSED,
            )
    return outcomes, tuple(sorted(uncollectable))


def _statuses(
    known: set[NodeId],
    outcomes: Mapping[tuple[str, str], TestStatus],
    uncollectable: tuple[str, ...],
) -> Mapping[NodeId, TestStatus]:
    """Key the run's outcomes by node id, the vocabulary everything above this module uses.

    An id the report says nothing about is *absent* rather than guessed at, with one
    exception: an id whose file would not import did not run for a reason the run stated, and
    that reason is ``collect_error``. At a parent commit it is the ordinary shape of red - a
    new test importing something the fix adds - which is why the status exists at all.
    """
    files = frozenset(uncollectable)
    statuses: dict[NodeId, TestStatus] = {}
    for node_id in sorted(known):
        outcome = outcomes.get(_junit_key(node_id))
        if outcome is not None:
            statuses[node_id] = outcome
        elif node_id.partition("::")[0] in files:
            statuses[node_id] = TestStatus.COLLECT_ERROR
    return MappingProxyType(statuses)


def _junit_key(node_id: NodeId) -> tuple[str, str]:
    """Map ``pkg/test_m.py::TestThing::test_p[1]`` to ``("pkg.test_m.TestThing", "test_p[1]")``.

    Every ``::`` segment but the last nests into the classname alongside the dotted module
    path; the last is the test's own name, parametrisation and all. This assumes pytest's
    rootdir is the workspace - the same assumption the node ids themselves carry, since the
    collection pass that produced them printed them rootdir-relative.
    """
    path, _, rest = node_id.partition("::")
    segments = rest.split("::")
    module = path.removesuffix(".py").replace("/", ".")
    return ".".join((module, *segments[:-1])), segments[-1]


def _module_path(dotted: str) -> str:
    """Map a dotted module name back to the repo-relative POSIX file it was imported from."""
    return f"{dotted.replace('.', '/')}.py"


def _remaining(deadline: float) -> int:
    """Seconds left before ``deadline``, never below one - a zero budget kills on the spot."""
    return max(1, int(deadline - monotonic()))
