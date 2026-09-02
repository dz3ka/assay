"""What the sandbox runner reports, and the assumption the whole image design rests on.

The runner is the join between three things measured separately: the image (built once, from a
commit), the container policy (no network, one writable directory, a ceiling), and
:func:`assay.host.junit.build_test_report`, which is the *host* runner's report builder and is
reused rather than reimplemented. So these tests run pytest for real, inside a real container,
over a real worktree - a mock would retire none of the three.

The workspace they mount is deliberately **not** the tree the image was built from: two test
files are added to it afterwards. An image whose copy of the repository were what ran would
collect neither of them, so a green run is evidence that the bind mount is what the trial sees.

There is no skip path (ADR-0024, and see ``tests/sandbox/support.py``).
"""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from assay.host import PytestHostRunner, SelectorError
from assay.mine import pytest_selectors
from assay.mine.models import NodeId
from assay.mine.models import TestReport as Report
from assay.mine.models import TestStatus as Status
from assay.mine.protocols import TestRunner as Runner
from assay.sandbox import (
    VENV_PYTHON,
    WORKSPACE_DIR,
    SandboxError,
    SandboxTestRunner,
    run_in_sandbox,
    sandbox_runner_for,
)
from tests.sandbox.support import TRIAL_LIMITS, fixture_image, running_containers_from

# Enough for two container starts and a four-test suite, well short of a hung daemon.
_RUN_BUDGET_S = 180

# What the endless test below is given, and how long the container it leaves behind is then
# allowed to take to disappear.
_DOOMED_BUDGET_S = 5
_SETTLE_S = 30.0

# Added to the worktree *after* the image is built. It imports the fixture project, so it can
# only pass if the code the container imports is the mounted tree.
_MOUNTED_TEST = """\
from widget.calc import total


def test_added_after_the_image_was_built() -> None:
    assert total([2.0, 3.0]) == 5.0
"""

_ENDLESS_TEST = """\
import time


def test_never_finishes() -> None:
    time.sleep(600)
"""

_MOUNTED: NodeId = "tests/test_mounted.py::test_added_after_the_image_was_built"
_ORIGINAL: NodeId = "tests/test_calc.py::test_total_adds_the_values"

# ``-P`` keeps the interpreter from putting the working directory on ``sys.path``. Without it
# this probe would prove nothing: the container's working directory *is* ``/workspace``, so the
# import would succeed whether or not the build's editable install survived the bind mount.
_IMPORT_PROBE = "import widget.calc; print(widget.calc.__file__)"


@pytest.fixture(scope="module")
def trial(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, str]]:
    """A built image, and a workspace that has grown two test files since it was built."""
    with fixture_image(tmp_path_factory.mktemp("runner")) as (workspace, tag):
        (workspace / "tests" / "test_mounted.py").write_text(_MOUNTED_TEST, encoding="utf-8")
        (workspace / "tests" / "test_endless.py").write_text(_ENDLESS_TEST, encoding="utf-8")
        yield workspace, tag


def _runner(trial: tuple[Path, str], out_root: Path) -> Runner:
    """The runner under test, made the way production will make it - through the factory."""
    workspace, tag = trial
    made = sandbox_runner_for(tag, limits=TRIAL_LIMITS, out_root=out_root)(workspace)
    assert made is not None, "a sandbox runner has nothing to provision and cannot decline"
    return made


def test_a_sandbox_run_reports_the_statuses_pytest_produced_in_the_container(
    trial: tuple[Path, str], tmp_path: Path
) -> None:
    workspace, _ = trial

    report: Report = _runner(trial, tmp_path).run(
        workspace,
        ("tests/test_calc.py", "tests/test_mounted.py"),
        timeout_s=_RUN_BUDGET_S,
    )

    assert report.timed_out is False
    assert report.exit_code == 0
    assert report.uncollectable == ()
    assert report.statuses[_ORIGINAL] == Status.PASSED
    # The file the image has never seen. It ran, and it imported the project, so the trial's
    # code and the trial's environment came from two different places on purpose.
    assert report.statuses[_MOUNTED] == Status.PASSED
    # Nothing was left on the host: the trial's junit report is read and its directory goes.
    assert list(tmp_path.iterdir()) == []


def test_the_editable_install_resolves_the_mounted_workspace_not_a_copy(
    trial: tuple[Path, str], tmp_path: Path
) -> None:
    """The premise the image design rests on, pinned in shipped code rather than in a probe.

    ``uv pip install -e /workspace`` at build time leaves a ``.pth`` file in the venv's
    site-packages holding the single line ``/workspace``, so imports resolve through
    ``sys.path`` at run time - and therefore through whatever is mounted there. If that stopped
    holding, every trial would silently score the copy baked into the image instead of the
    checkout it was handed.

    Asserted with an interpreter probe rather than with the pytest run above, because the SPEC
    §9 fixture ships a root ``conftest.py`` on purpose (it is the shape most repositories have),
    and pytest's prepend import mode puts a conftest's own directory on ``sys.path``. A green
    pytest run is therefore consistent with the editable install having vanished; this is not.
    """
    workspace, tag = trial

    result = run_in_sandbox(
        image_tag=tag,
        workspace=workspace,
        out_dir=tmp_path,
        argv=(VENV_PYTHON, "-P", "-c", _IMPORT_PROBE),
        limits=TRIAL_LIMITS,
        timeout_s=_RUN_BUDGET_S,
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == f"{WORKSPACE_DIR}/widget/calc.py"


def test_a_run_that_outlives_its_budget_is_reported_as_timed_out(
    trial: tuple[Path, str], tmp_path: Path
) -> None:
    workspace, tag = trial

    report = _runner(trial, tmp_path).run(
        workspace, ("tests/test_endless.py",), timeout_s=_DOOMED_BUDGET_S
    )

    # The protocol's contract: a candidate that cannot be measured in time is discarded and
    # counted, so the runner answers with a report rather than raising and ending the walk.
    assert report.timed_out is True
    assert report.statuses == {}
    assert report.exit_code < 0, "a killed run has no exit code pytest could have produced"
    assert running_containers_from(tag, settle_s=_SETTLE_S) == ()


def test_a_run_whose_image_is_absent_reports_a_code_no_pytest_run_could_produce(
    trial: tuple[Path, str], tmp_path: Path
) -> None:
    """A tag that is not on this host, which is what ``docker image prune`` leaves behind.

    Two claims at once. The runner *reports* rather than raises, so the failure travels as a
    report like any other; and the code it reports is 125, the client's own, which no pytest run
    can produce (pytest's are 0 to 5). That is what
    ``tests/score/test_executable.py::test_an_exit_code_outside_pytests_own_band_scores_errored``
    reads as ``Outcome.ERRORED`` - so a pruned image is recorded as the harness failing rather
    than printed as the tool scoring zero, ground-truth adapter included.
    """
    workspace, _ = trial
    absent = SandboxTestRunner(
        f"assay-absent-{uuid4()}:missing", limits=TRIAL_LIMITS, out_root=tmp_path
    )

    report = absent.run(workspace, ("tests/test_calc.py",), timeout_s=_RUN_BUDGET_S)

    assert report.exit_code == 125
    assert report.timed_out is False, "nothing was killed: the container never started"
    assert report.statuses == {}
    assert report.uncollectable == ()


def test_a_selector_that_would_be_read_as_an_option_is_refused(
    trial: tuple[Path, str], tmp_path: Path
) -> None:
    workspace, _ = trial

    # Loud rather than filtered, and before any container starts: dropping it silently would run
    # a smaller suite than the gate believes it ran. The same rule as the host runner's, because
    # the two are interchangeable behind one protocol.
    with pytest.raises(SandboxError, match="command-line option"):
        _runner(trial, tmp_path).run(workspace, ("-x",), timeout_s=_RUN_BUDGET_S)


@pytest.mark.parametrize("selector", ["-x", "--co", ""], ids=["option", "long-option", "empty"])
def test_the_selection_a_runner_refuses_is_the_selection_the_miner_never_produces(
    selector: str, tmp_path: Path
) -> None:
    """The third spelling of one rule, pinned against the two that raise (ADR-0029).

    ``assay.mine.pytest_selectors`` decides a runnable selector, and each runner refuses an
    unrunnable one on its own side of the wall - three copies of six lines, licensed the way
    ADR-0012 licenses a constraint spelled twice, because sharing them would make
    :mod:`assay.mine` import a package it is forbidden to know about. Drift between them is the
    failure this asserts away: a shape the miner passes on and a runner refuses ends a mining
    walk that should have discarded one candidate.

    No image and no daemon: both refusals fire before any process starts, so the runners are
    constructed here rather than taken from the module fixture.
    """
    assert pytest_selectors((selector,)) == ()

    with pytest.raises(SelectorError):
        PytestHostRunner(Path("python")).run(tmp_path, (selector,), timeout_s=_RUN_BUDGET_S)
    with pytest.raises(SandboxError):
        SandboxTestRunner("assay-never-built:missing", limits=TRIAL_LIMITS, out_root=tmp_path).run(
            tmp_path, (selector,), timeout_s=_RUN_BUDGET_S
        )
