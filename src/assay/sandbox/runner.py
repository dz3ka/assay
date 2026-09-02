"""The ``TestRunner`` that runs a repository's tests inside a container instead of on the host.

The sandbox twin of :mod:`assay.host.pytest_runner`, and deliberately its mirror image: two
bounded pytest invocations, a junit report, and :func:`assay.host.junit.build_test_report` -
*the same* function, not a second spelling of the same rules. A harness whose two runners could
disagree about one run would be a harness whose numbers depend on where the test happened to be
executed, which is the one thing this project may not be.

What differs is only where the run happens and where its report lands. The workspace is mounted
read only, so the junit XML cannot be written beside the tests the way the host runner writes it
into a temporary file; it goes to :data:`assay.sandbox.OUT_DIR`, which is the trial's one
writable bind mount, and the host reads it back out of the directory it mounted there.

Nothing in this module knows a trial policy: which flags make a container safe is
:mod:`assay.sandbox.container`'s single answer, and this module is one of its callers.
"""

import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from time import monotonic
from types import MappingProxyType
from typing import Final

from assay.host.junit import build_test_report
from assay.host.process import CommandResult, CommandTimeoutError
from assay.mine.models import TestReport
from assay.mine.protocols import RunnerFactory, TestRunner
from assay.sandbox.container import OUT_DIR, run_in_sandbox
from assay.sandbox.errors import SandboxError
from assay.sandbox.image import VENV_PYTHON
from assay.sandbox.models import ContainerLimits

# Flags on every invocation, for the reasons :mod:`assay.host.pytest_runner` gives: ``-q`` is
# the format the collected node ids are read back out of, and ``-p no:cacheprovider`` keeps a
# ``.pytest_cache`` out of the workspace. Inside a container the cache would be refused by the
# read-only mount anyway - but silently, and a run whose flags depend on which side of the
# sandbox wall it is on is a run the two runners could report differently.
_ALWAYS: Final = ("-p", "no:cacheprovider", "-q")

# Where the trial writes its report, on the container's side of the mount.
_JUNIT_NAME: Final = "junit.xml"
_CONTAINER_JUNIT: Final = f"{OUT_DIR}/{_JUNIT_NAME}"

# The exit code reported when a run was killed at its budget, and the same value the host runner
# uses: negative so it can never be mistaken for one of pytest's own, which are 0 to 5.
_KILLED_EXIT_CODE: Final = -1


class SandboxTestRunner:
    """Runs a workspace's pytest suite inside a task image built from that workspace's commit.

    Args:
        image_tag: The task image, from :func:`assay.sandbox.build_task_image`. Pinned to a
            commit by construction, so a runner made for one base commit cannot be pointed at
            another workspace's tests without saying so.
        limits: The resource ceiling every trial this runner starts will run under.
        out_root: A host directory the runner may create per-run scratch directories under. One
            per run, because a report left behind from the previous run is a report this one
            could read as its own.

    Satisfies :class:`assay.mine.protocols.TestRunner` structurally, the way
    :class:`assay.host.PytestHostRunner` does: no base class, conformance proved by
    ``mypy --strict`` where a ``TestRunner`` is annotated.
    """

    def __init__(self, image_tag: str, *, limits: ContainerLimits, out_root: Path) -> None:
        self._image_tag = image_tag
        self._limits = limits
        self._out_root = out_root

    def run(self, workspace: Path, selectors: Sequence[str], *, timeout_s: int) -> TestReport:
        """Run ``selectors`` against ``workspace`` in a container and report what happened.

        The budget covers both invocations, as it does on the host: the collection pass is
        charged against it and the measuring pass gets what is left, so ``timeout_s`` is a
        ceiling on the run rather than an allowance that can be paid twice. A run that hits it
        returns a report with ``timed_out`` set and no statuses - the container is already dead
        by then, killed by :func:`assay.sandbox.run_in_sandbox`.

        Raises:
            SandboxError: if a selector is empty or could be read as a command-line option.
        """
        checked = tuple(_checked_selector(selector) for selector in selectors)
        deadline = monotonic() + timeout_s
        out_dir = Path(tempfile.mkdtemp(prefix="assay-trial-", dir=self._out_root))
        try:
            try:
                collected = self._pytest(
                    workspace, out_dir, "--collect-only", *checked, timeout_s=_remaining(deadline)
                )
                measured = self._pytest(
                    workspace,
                    out_dir,
                    f"--junit-xml={_CONTAINER_JUNIT}",
                    *checked,
                    timeout_s=_remaining(deadline),
                )
            except CommandTimeoutError:
                return TestReport(
                    statuses=MappingProxyType({}),
                    uncollectable=(),
                    exit_code=_KILLED_EXIT_CODE,
                    timed_out=True,
                )
            junit_xml = _junit_text(out_dir / _JUNIT_NAME)
        finally:
            # The trial's whole output, and it has been read. Left behind it would be one
            # directory per trial per task per repetition on the host that mounted it.
            shutil.rmtree(out_dir, ignore_errors=True)

        return build_test_report(
            collected_stdout=collected.stdout,
            junit_xml=junit_xml,
            selectors=checked,
            exit_code=measured.exit_code,
        )

    def _pytest(
        self, workspace: Path, out_dir: Path, *arguments: str, timeout_s: int
    ) -> CommandResult:
        """One pytest invocation, in its own container. Pytest's exit code is the answer."""
        return run_in_sandbox(
            image_tag=self._image_tag,
            workspace=workspace,
            out_dir=out_dir,
            argv=(VENV_PYTHON, "-m", "pytest", *_ALWAYS, *arguments),
            limits=self._limits,
            timeout_s=timeout_s,
        )


def sandbox_runner_for(image_tag: str, *, limits: ContainerLimits, out_root: Path) -> RunnerFactory:
    """A :data:`assay.mine.RunnerFactory` that gives every workspace the same sandbox runner.

    The sandbox counterpart of ``assay.cli.host_runner_for``, and much the smaller of the two.
    On the host a runner cannot exist before its workspace does, because the environment is
    provisioned *into* the worktree - which is why the seam is a factory at all. Here the
    environment was built into an image when the task was mined, so there is nothing left to do
    per workspace and nothing left to fail: a workspace is an argument to
    :meth:`SandboxTestRunner.run`, not a thing the runner is made from.

    It therefore never answers ``None``. ``None`` means "this commit cannot be given an
    environment its tests could run in", and a commit whose image would not build never became a
    task in the first place.
    """
    runner = SandboxTestRunner(image_tag, limits=limits, out_root=out_root)

    def make_runner(workspace: Path) -> TestRunner | None:
        return runner

    return make_runner


def _checked_selector(value: str) -> str:
    """Refuse a selector that would be read as an option rather than as a test to run.

    The same rule as :mod:`assay.host.pytest_runner`'s, and deliberately a second copy of six
    lines rather than a shared helper: the two runners are interchangeable behind one protocol,
    so they have to refuse the same input, and the rule is about the argv each one builds. A
    dropped selector would run a smaller suite than the gate believes it ran, so this is loud.

    The refusal is a :class:`~assay.sandbox.SandboxError` - everything this package refuses is
    one - where the host copy's is :class:`assay.host.SelectorError`. Two classes, one base:
    each error lives in the package that raises it, and the base is how :mod:`assay.cli` ends a
    command on one sentence rather than a traceback. Nothing catches either refusal per row; the
    recorded outcome that does exist is :func:`assay.host.provision_venv`'s, caught at the host
    seam in ``assay.cli.host_runner_for`` and counted ``unprovisioned``. A mining walk never
    arrives here in any case, since :func:`assay.mine.pytest_selectors` decides usability on the
    task's own data first (ADR-0029), which leaves :func:`assay.score.run_trial` and its recorded
    node ids as the one caller a refusal still ends - the residue ADR-0029 names.
    """
    if not value:
        raise SandboxError("a test selector is empty")
    if value.startswith("-"):
        raise SandboxError(f"selector would be read as a command-line option: {value!r}")
    return value


def _junit_text(path: Path) -> str | None:
    """The report the trial wrote, or ``None`` when there is nothing readable to hand on.

    A missing file is no evidence rather than an error, exactly as on the host: pytest writes
    the report as it exits, and a mined test that takes the process down with it leaves nothing
    behind. Inside a container there is a second way to arrive here - the container died for a
    reason of its own, out of memory above all - and it means the same thing.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _remaining(deadline: float) -> int:
    """Seconds left before ``deadline``, never below one - a zero budget kills on the spot."""
    return max(1, int(deadline - monotonic()))
