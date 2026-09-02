"""Reading one junit XML report into the :class:`~assay.mine.models.TestReport` above it.

Text in, report out: nothing here opens a file, starts a process or learns where the XML came
from. That is the point of the split. The mining gate reads a report written by a pytest run
on this host (:mod:`assay.host.pytest_runner`) and M2's scorer reads one written by a pytest
run inside a sandbox; a second, independently written spelling of these rules would let the two
disagree about a single run, which is the one thing a harness about measurement may not do.

The XML is keyed by ``(classname, name)``, not by node id, so this module maps each *known* id
forward into that pair. Forward, never backward: ``classname="pkg.test_deep.TestThing"`` cannot
be turned back into a path and a class without guessing which dots were slashes, and Assay owns
the id set, so the direction that needs no guess is the one available.

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
"""

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final
from xml.etree import ElementTree

from assay.mine.models import NodeId, TestReport, TestStatus, is_node_id

# The junit child element a status is read from. ``skipped`` is absent on purpose - see the
# module docstring - and a testcase with no child element at all is a pass.
_STATUS_BY_ELEMENT: Final = MappingProxyType(
    {"failure": TestStatus.FAILED, "error": TestStatus.ERRORED}
)


def build_test_report(
    *,
    collected_stdout: str,
    junit_xml: str | None,
    selectors: Sequence[str],
    exit_code: int,
) -> TestReport:
    """Turn what one pytest run printed and wrote into the report the gate decides on.

    Args:
        collected_stdout: stdout of the ``--collect-only -q`` pass, which is where the node
            ids a selection actually resolved to come from.
        junit_xml: the ``--junit-xml`` report as text, or ``None`` when the run left nothing
            readable behind. ``None`` and unparsable XML mean the same thing here - no
            statuses and no uncollectable files - because a report that cannot be read is
            evidence of nothing, and the gate discards the runs that produce it.
        selectors: what the run was asked to execute. Those that are node ids are known ids in
            their own right: a run that refused its selection prints none of them, and an id
            Assay named is still an id a task can carry.
        exit_code: pytest's own code, raw. Never translated - the gate reads it.

    Returns:
        A report with ``timed_out`` false. A run killed at its budget produced no evidence to
        read, so its report is built by the caller that did the killing.
    """
    outcomes, uncollectable = _read_junit(junit_xml)
    known = _collected_ids(collected_stdout) | {s for s in selectors if is_node_id(s)}
    return TestReport(
        statuses=_statuses(known, outcomes, uncollectable),
        uncollectable=uncollectable,
        exit_code=exit_code,
        timed_out=False,
    )


def _collected_ids(output: str) -> set[NodeId]:
    """The node ids ``--collect-only -q`` printed, and nothing else that it printed.

    ``-q`` prints one id per line and then a summary, and a collection error adds a traceback
    - so the filter is :func:`assay.mine.models.is_node_id`, the miner's own definition of an
    id it is willing to put in a task, rather than a line count. Measured: collection still
    prints the ids it *did* resolve when the same argv also names one it could not (exit 4),
    so this set is trustworthy even on a run that then refused to execute anything.
    """
    return {line for line in (raw.strip() for raw in output.splitlines()) if is_node_id(line)}


def _read_junit(text: str | None) -> tuple[Mapping[tuple[str, str], TestStatus], tuple[str, ...]]:
    """Read one junit report into ``(status by (classname, name), uncollectable files)``.

    Absent or truncated XML is read as no evidence rather than raised on: pytest writes the
    report as it exits, and a mined test that takes the process down with it (``os._exit``, a
    segfault) leaves nothing to parse. Such a run reports no statuses and a non-zero exit
    code, which every rule in :mod:`assay.mine.gate` discards - the conservative direction.
    """
    if text is None:
        return {}, ()
    try:
        # Parsed from bytes rather than from the string: pytest's report opens with an
        # ``encoding="utf-8"`` declaration, and ElementTree refuses a ``str`` carrying one.
        root = ElementTree.fromstring(text.encode("utf-8"))
    except ElementTree.ParseError:
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
