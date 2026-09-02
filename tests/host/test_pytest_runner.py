"""What one pytest run is allowed to tell the gate, and how each shape of it is told apart.

The gate (SPEC §3) decides a commit's fate on four things: which tests passed, which files
would not collect, the raw exit code, and whether the run was killed. Everything here is a
real pytest 9.1.1 subprocess over a throwaway package under ``tmp_path``, because the
behaviour being pinned is pytest's and not a parser's - including the two shapes that are
easy to get wrong from the outside: a module that raises at import time (which aborts the
whole run) and a node id that does not resolve (which refuses the whole selection with exit
4 while its valid siblings never run).

The one exception is the last test in this file: the one-second floor under a shared
deadline has no path to a real run that would show it, which is why ADR-0016 left it
unpinned and named the test below as its follow-up.

``TestReport``/``TestRunner``/``TestStatus`` are imported under aliases: pytest collects any
module-level ``Test*`` class, and importing them under their own names would warn on every
run of this file.
"""

import sys
from pathlib import Path
from time import monotonic

import pytest

from assay.core import AssayError
from assay.host import PytestHostRunner, SelectorError
from assay.host.pytest_runner import _remaining
from assay.mine.models import TestStatus as Status
from assay.mine.protocols import TestRunner as Runner

# Conformance to the protocol the miner is written against, proved statically by
# ``mypy --strict`` here rather than by an ``isinstance`` that could only check names.
_: Runner = PytestHostRunner(Path(sys.executable))

# A budget nothing but the deliberate hang below runs into: these suites hold five tests.
_BUDGET_S = 120

_GOOD_MODULE = """\
import pytest


def setup_function(function):
    if function.__name__ == "test_errors_in_setup":
        raise RuntimeError("boom in setup")


def test_plain():
    assert True


def test_fails():
    assert 1 == 2


def test_errors_in_setup():
    assert True


class TestThing:
    @pytest.mark.parametrize("n", [1, 2])
    def test_p(self, n):
        assert n > 0
"""

# Raises on import, so pytest never collects the test below it. This is the ordinary shape of
# a red run at a parent commit: a new test importing something the fix has not added yet.
_BAD_MODULE = """\
raise ImportError("this module refuses to import")


def test_never():
    assert True
"""


def _runner() -> PytestHostRunner:
    """The interpreter running this suite, which is the one that has pytest installed.

    Real provisioning is :func:`assay.host.provision_venv` and is tested next door; what is
    under test here is the reading of a run, so the environment is borrowed rather than built.
    """
    return PytestHostRunner(Path(sys.executable))


def _workspace(root: Path, **modules: str) -> Path:
    """Write ``pkg/sub/<name>.py`` for each keyword, with the ``__init__.py`` files around it."""
    package = root / "pkg" / "sub"
    package.mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8", newline="\n")
    (package / "__init__.py").write_text("", encoding="utf-8", newline="\n")
    for name, source in modules.items():
        (package / f"{name}.py").write_text(source, encoding="utf-8", newline="\n")
    return root


def test_a_run_reports_every_collected_test_under_its_own_node_id(tmp_path: Path) -> None:
    # Four statuses from one run, keyed the way the gate compares two runs: a plain pass, an
    # assertion failure, an error raised in setup rather than in the test body, and the two
    # parametrised cases of a method on a class - which junit spells as a nested classname.
    workspace = _workspace(tmp_path, test_deep=_GOOD_MODULE)

    report = _runner().run(workspace, ["pkg/sub/test_deep.py"], timeout_s=_BUDGET_S)

    assert dict(report.statuses) == {
        "pkg/sub/test_deep.py::TestThing::test_p[1]": Status.PASSED,
        "pkg/sub/test_deep.py::TestThing::test_p[2]": Status.PASSED,
        "pkg/sub/test_deep.py::test_errors_in_setup": Status.ERRORED,
        "pkg/sub/test_deep.py::test_fails": Status.FAILED,
        "pkg/sub/test_deep.py::test_plain": Status.PASSED,
    }
    assert report.uncollectable == ()
    assert report.exit_code == 1
    assert not report.timed_out


def test_a_module_that_will_not_import_is_a_collect_error_and_names_its_file(
    tmp_path: Path,
) -> None:
    # The fourth status. The file is named repo-relative and POSIX, because that is what a
    # task carries to a Linux replay host, and the selected id gets a status of its own -
    # "did not run because its module would not import" is evidence, not silence.
    workspace = _workspace(tmp_path, test_bad=_BAD_MODULE)

    report = _runner().run(workspace, ["pkg/sub/test_bad.py::test_never"], timeout_s=_BUDGET_S)

    assert report.uncollectable == ("pkg/sub/test_bad.py",)
    assert dict(report.statuses) == {"pkg/sub/test_bad.py::test_never": Status.COLLECT_ERROR}
    assert not report.timed_out


def test_one_unimportable_module_costs_the_whole_run_its_siblings(tmp_path: Path) -> None:
    # Measured, and the reason the gate may not read "no statuses" as "nothing failed": a
    # single collection error aborts the run, so the perfectly good module in the same argv
    # never executes. The report has to say so rather than report an empty green.
    workspace = _workspace(tmp_path, test_deep=_GOOD_MODULE, test_bad=_BAD_MODULE)

    report = _runner().run(workspace, ["pkg/sub"], timeout_s=_BUDGET_S)

    assert report.uncollectable == ("pkg/sub/test_bad.py",)
    assert dict(report.statuses) == {}
    assert report.exit_code != 0


def test_an_unresolvable_node_id_refuses_the_selection_rather_than_running_the_rest(
    tmp_path: Path,
) -> None:
    # pytest exit 4, its usage error: the whole argv is refused and the valid sibling is not
    # run. ``assay.mine.gate`` reads exactly this shape - exit 4 with no statuses - as
    # evidence that the target tests do not exist at the parent commit, so the runner must
    # surface the code untouched instead of translating it into a harness failure.
    workspace = _workspace(tmp_path, test_deep=_GOOD_MODULE)

    report = _runner().run(
        workspace,
        ["pkg/sub/test_deep.py::test_plain", "pkg/sub/test_deep.py::test_absent"],
        timeout_s=_BUDGET_S,
    )

    assert report.exit_code == 4
    assert dict(report.statuses) == {}
    assert report.uncollectable == ()
    assert not report.timed_out


def test_a_selection_that_collects_nothing_is_exit_five_and_not_an_error(tmp_path: Path) -> None:
    # Measured here for the first time (the plan carried exit 5 as unverified): a file with no
    # tests in it exits 5 with an empty testsuite, distinct from the exit 4 above. Nothing
    # interprets 5 yet; this test is what will tell us if a pytest upgrade changes it.
    workspace = _workspace(tmp_path, test_empty="")

    report = _runner().run(workspace, ["pkg/sub/test_empty.py"], timeout_s=_BUDGET_S)

    assert report.exit_code == 5
    assert dict(report.statuses) == {}
    assert report.uncollectable == ()


def test_a_run_that_outlives_its_budget_is_reported_rather_than_raised(tmp_path: Path) -> None:
    # The protocol's contract: a candidate that cannot be measured in time is discarded and
    # counted, so the miner keeps walking instead of dying on one pathological repository.
    workspace = _workspace(
        tmp_path, test_slow="import time\n\n\ndef test_slow():\n    time.sleep(120)\n"
    )

    report = _runner().run(workspace, ["pkg/sub/test_slow.py"], timeout_s=1)

    assert report.timed_out
    assert dict(report.statuses) == {}


def test_no_pytest_cache_is_left_behind_in_the_workspace(tmp_path: Path) -> None:
    # A worktree is scored by ``git diff`` after a tool has worked in it, so a directory Assay
    # created there would be Assay's own contribution to the answer.
    workspace = _workspace(tmp_path, test_deep=_GOOD_MODULE)

    _runner().run(workspace, ["pkg/sub/test_deep.py::test_plain"], timeout_s=_BUDGET_S)

    assert not (workspace / ".pytest_cache").exists()
    assert list(workspace.glob("*.xml")) == []


@pytest.mark.parametrize(
    "selector",
    ["", "-k", "--collect-only"],
    ids=["empty", "short option", "long option"],
)
def test_a_selector_that_would_change_the_command_is_refused(tmp_path: Path, selector: str) -> None:
    # Node ids are built from a mined repository's own file names. One that reaches the argv
    # as an option would silently run a different suite than the one the gate is deciding on.
    with pytest.raises(SelectorError, match="selector"):
        _runner().run(tmp_path, [selector], timeout_s=_BUDGET_S)


def test_a_refused_selector_is_catchable_as_an_assay_error(tmp_path: Path) -> None:
    """The base class is the point, not the name: a walk catches ``AssayError`` to *record* it.

    ``assay.host.git`` and ``assay.host.venv`` both turn a failure into a per-commit outcome by
    catching that base, and the miner counts what they return. A refusal that escaped this
    module as the bare ``ValueError`` it once was would pass straight through those handlers,
    so one malformed node id would cost a whole walk its measurement instead of one row. The
    sandbox runner's identical refusal is pinned the same way in ``tests/sandbox/test_image``.
    """
    with pytest.raises(AssayError, match="selector"):
        _runner().run(tmp_path, ["--collect-only"], timeout_s=_BUDGET_S)


def test_an_exhausted_deadline_still_buys_one_second_rather_than_zero() -> None:
    # ADR-0016's named follow-up, and the only unexercised rule in this module: both passes
    # are charged against one deadline, so the measuring pass routinely asks for what a slow
    # collection pass already spent. A budget of zero reaches ``run_command`` as a kill on the
    # spot - a child that never started is evidence of nothing, where a one-second run at
    # least reports a timeout the yield can count. Deliberate, not an accident of ``max``.
    assert _remaining(monotonic() - 5.0) == 1
    assert _remaining(monotonic()) == 1
