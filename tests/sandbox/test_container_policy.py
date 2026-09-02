"""The three negatives SPEC §9 asks for, proved about the path a real trial takes.

A trial cannot reach the network, cannot write outside the one directory it is given, and is
killed at its resource limit. Each of those is asserted here by calling
:func:`assay.sandbox.run_in_sandbox` - the same function :class:`assay.sandbox.SandboxTestRunner`
calls - and never by assembling a ``docker`` command line in a test. A test that wrote its own
argv would prove that *that* argv is safe, which is a claim about the test.

A fourth negative is proved here as well, and it comes from SPEC §5.1 rather than §9: a trial
whose image is missing from this host does not go and look for one. The task image *is* the
repository under evaluation (:mod:`assay.sandbox.image`), so a registry round trip taken from
inside the trial path would be the one thing this harness may never do.

There is no skip path and no "docker not available" guard (ADR-0024, and see
``tests/sandbox/support.py``): a network-off proof that quietly does not run is exactly the
failure this project exists to catch.

The probes are run with the venv interpreter the image was built around rather than with a shell
utility, because it is the interpreter a trial actually runs and because its errors are
structured - ``socket.gaierror`` and ``errno`` are not messages that vary between base images.
"""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from assay.host import CommandTimeoutError
from assay.host.junit import build_test_report
from assay.results import Outcome
from assay.sandbox import OUT_DIR, VENV_PYTHON, WORKSPACE_DIR, ContainerLimits, run_in_sandbox
from assay.score import score_report
from assay.suite import Task
from tests.sandbox.support import TRIAL_LIMITS, fixture_image, running_containers_from

# Long enough for a container to start, run one short probe and stop; short enough that a
# wedged daemon fails the suite rather than holding it.
_PROBE_BUDGET_S = 120

# The budget the wall-clock test hands a probe that sleeps far longer than it, and how long the
# container it kills is then given to disappear from `docker ps`.
_DOOMED_BUDGET_S = 5
_SETTLE_S = 30.0

# Small enough to be refused quickly, and still enough for CPython to start: the probe below has
# to reach its allocation before it can be killed for making it.
_STARVED = ContainerLimits(memory_mb=64, cpus="1", pids=256)

_HOSTNAME_PROBE = "import socket; socket.gethostbyname('example.com')"

# A raw address, so that "the network is off" is not confused with "DNS is off". 1.1.1.1:443 is
# reachable from any host with an internet connection, and the timeout is what stops this
# becoming a slow test on a host that has none - a connection *refused* would also fail the
# assertion below, which is the point: the error must be the absence of an interface.
_ADDRESS_PROBE = "import socket; socket.create_connection(('1.1.1.1', 443), timeout=5)"

# Every place a trial might try to write, and the answer expected at each. `/workspace` is the
# tree the trial is scored against, `/etc` stands for the container's own root filesystem, and
# `/opt/venv` is the environment the red->green gate validated - a trial that could edit any of
# the three could edit the measurement rather than pass it.
_WRITE_PROBE = f"""
import pathlib
for target in ({WORKSPACE_DIR!r}, '/etc', '/opt/venv', {OUT_DIR!r}):
    probe = pathlib.Path(target) / 'assay-write-probe'
    try:
        probe.write_text('x')
    except OSError:
        print(target, 'refused')
    else:
        print(target, 'written')
"""

# Well past the ceiling `_STARVED` allows, and written as a `bytearray` because it is zeroed:
# an allocation the process never touches is one the kernel never has to find pages for.
_MEMORY_PROBE = "buf = bytearray(400 * 1024 * 1024); print('allocated', len(buf))"

_SLEEP_PROBE = "import time; time.sleep(600)"

# The ids a task would have been scored on, had the probe above been a trial's test run. Any two
# ids do: the OOM verdict is decided before a single recorded id is looked at, and a task that
# named the fixture's own tests would suggest otherwise.
_TARGET_SELECTORS = ("tests/test_widget.py::test_target",)


def _starved_task() -> Task:
    """A task in the shape a suite on disk carries, built the way ``tests/score`` builds one.

    Nothing here is measured - the workspace under test is the fixture repository and the probe
    is not its suite. It exists because :func:`assay.score.score_report` takes a task, and the
    branch under test answers before it reads one.
    """
    return Task(
        schema_version=1,
        task_id="widget-fixture-000000000000",
        repo_url="https://example.invalid/widget.git",
        base_commit="0" * 40,
        test_files=("tests/test_widget.py",),
        test_patch="",
        ground_truth_patch="",
        fail_to_pass=_TARGET_SELECTORS,
        pass_to_pass=(),
        prompt="make the target pass",
        metadata={},
    )


@pytest.fixture(scope="module")
def trial(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, str]]:
    """The workspace and image every probe below runs against, built once for the module."""
    with fixture_image(tmp_path_factory.mktemp("policy")) as built:
        yield built


def test_a_trial_cannot_resolve_a_hostname(trial: tuple[Path, str], tmp_path: Path) -> None:
    workspace, tag = trial

    result = run_in_sandbox(
        image_tag=tag,
        workspace=workspace,
        out_dir=tmp_path,
        argv=(VENV_PYTHON, "-c", _HOSTNAME_PROBE),
        limits=TRIAL_LIMITS,
        timeout_s=_PROBE_BUDGET_S,
    )

    assert result.exit_code != 0, "a trial resolved a hostname"
    assert "gaierror" in result.stderr


def test_a_trial_cannot_reach_a_raw_ip_address(trial: tuple[Path, str], tmp_path: Path) -> None:
    workspace, tag = trial

    result = run_in_sandbox(
        image_tag=tag,
        workspace=workspace,
        out_dir=tmp_path,
        argv=(VENV_PYTHON, "-c", _ADDRESS_PROBE),
        limits=TRIAL_LIMITS,
        timeout_s=_PROBE_BUDGET_S,
    )

    assert result.exit_code != 0, "a trial opened a socket to a raw address"
    # ENETUNREACH: there is no interface to route from, which is the shape `--network none`
    # produces. A refused connection or a timeout would mean something else was wrong.
    assert "Network is unreachable" in result.stderr


def test_a_trial_whose_image_is_absent_is_refused_here_rather_than_pulled(tmp_path: Path) -> None:
    """``--pull never``, asserted by its consequence: a missing tag fails without a registry.

    The image is built on this host and never pushed anywhere, so a tag that is not here is a
    harness fault - ``docker image prune`` between mining and running is the everyday cause -
    and the honest answer is to fail locally. **Measured on this host** with the default policy
    the client prints ``Unable to find image ... locally`` and then asks a registry, which
    answers ``pull access denied`` for a repository that exists nowhere but here: a network
    round trip from inside the trial path, contradicting SPEC §5.1 and taking seconds to do it.

    No image is built for this test and none of the module's fixture is needed: an absent tag is
    refused before a mount, a limit or an argv can matter.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    absent = f"assay-absent-{uuid4()}:missing"

    result = run_in_sandbox(
        image_tag=absent,
        workspace=workspace,
        out_dir=tmp_path,
        argv=(VENV_PYTHON, "-c", _HOSTNAME_PROBE),
        limits=TRIAL_LIMITS,
        timeout_s=_PROBE_BUDGET_S,
    )

    # 125 is the client's own failure code rather than the command's: the command never ran.
    # `assay.score.score_report` reads that band as `Outcome.ERRORED`, which is what keeps a
    # pruned image from being scored as the tool's failure.
    assert result.exit_code == 125, result.stderr
    assert f"No such image: {absent}" in result.stderr
    printed = result.stdout + result.stderr
    assert "Unable to find image" not in printed, "the client went looking for the image"
    assert "pull access denied" not in printed, "the client reached a registry"


def test_a_trial_may_write_only_to_its_out_directory(
    trial: tuple[Path, str], tmp_path: Path
) -> None:
    workspace, tag = trial

    result = run_in_sandbox(
        image_tag=tag,
        workspace=workspace,
        out_dir=tmp_path,
        argv=(VENV_PYTHON, "-c", _WRITE_PROBE),
        limits=TRIAL_LIMITS,
        timeout_s=_PROBE_BUDGET_S,
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout.split("\n") == [
        f"{WORKSPACE_DIR} refused",
        "/etc refused",
        "/opt/venv refused",
        f"{OUT_DIR} written",
        "",
    ]
    # The write that was accepted really did land on the host's side of the mount, which is how
    # a trial hands its junit report and its patch back.
    assert (tmp_path / "assay-write-probe").read_text(encoding="utf-8") == "x"
    assert not (workspace / "assay-write-probe").exists()


def test_a_trial_is_killed_at_its_wall_clock_limit(trial: tuple[Path, str], tmp_path: Path) -> None:
    """The budget ends the trial, and the container with it.

    The second assertion is the one with a caveat worth stating. **Measured on this Windows
    host:** deleting the ``docker kill`` from :func:`assay.sandbox.run_in_sandbox` leaves this
    test green - the container is already gone by the time it is asked about, because
    ``run_command`` ends the client's process group with a console control event that the client
    is able to act on. *unverified:* on POSIX the group is ended with ``SIGKILL``, which no
    client can forward, so there the kill is what makes this assertion true. It is carried for
    that host and for CI, and this test is where CI reports whether it is enough.
    """
    workspace, tag = trial

    with pytest.raises(CommandTimeoutError) as raised:
        run_in_sandbox(
            image_tag=tag,
            workspace=workspace,
            out_dir=tmp_path,
            argv=(VENV_PYTHON, "-c", _SLEEP_PROBE),
            limits=TRIAL_LIMITS,
            timeout_s=_DOOMED_BUDGET_S,
        )

    assert raised.value.timeout_s == _DOOMED_BUDGET_S
    # A budget enforced only host-side would be a trial that outlives its own trial: the docker
    # CLI is a remote control, not a parent process, so ending it need not end what it started.
    assert running_containers_from(tag, settle_s=_SETTLE_S) == ()


def test_a_trial_is_killed_at_its_memory_limit(trial: tuple[Path, str], tmp_path: Path) -> None:
    """Killed by the kernel, not merely refused by the allocator.

    Exit 137 is SIGKILL, which is the cgroup's OOM killer and not a ``MemoryError`` the probe
    could have caught and reported as a passing test. It is also the one out-of-band code the
    scorer calls the tool's ``FAILED`` rather than the harness's ``ERRORED``, and the last
    assertion here is what binds that rule to a kill this test actually provoked.

    What a green run here does **not** prove is that ``--memory-swap`` is what did it: this host
    is WSL2, whose VM has no swap, so ``--memory`` alone already produces 137 (measured, see
    :mod:`assay.sandbox.image`). The flag
    is carried for hosts that do have swap, where without it this assertion would be a container
    paging for minutes instead of a container killed.
    """
    workspace, tag = trial

    result = run_in_sandbox(
        image_tag=tag,
        workspace=workspace,
        out_dir=tmp_path,
        argv=(VENV_PYTHON, "-c", _MEMORY_PROBE),
        limits=_STARVED,
        timeout_s=_PROBE_BUDGET_S,
    )

    assert result.exit_code == 137, result.stdout
    assert "allocated" not in result.stdout
    # And the verdict that code earns, read off the *measured* result rather than off a report
    # written by hand: a trial that ate the ceiling it was given failed, and is not the harness
    # erroring (ADR-0028). `build_test_report` is the same function
    # `assay.sandbox.SandboxTestRunner` would have called, and a container the kernel killed
    # leaves no junit behind - so this is the report shape a real OOM trial arrives with.
    killed = build_test_report(
        collected_stdout="",
        junit_xml=None,
        selectors=_TARGET_SELECTORS,
        exit_code=result.exit_code,
    )
    assert score_report(_starved_task(), killed) is Outcome.FAILED


# The capability set, asked twice over: once as a consequence and once as the kernel's own
# accounting. The consequence is `CAP_DAC_OVERRIDE`, the capability by which uid 0 ignores file
# permissions - the probe seals a file of its own inside its tmpfs and reads it back, which a
# root process holding the default set can do and one holding none cannot. The `/proc/self/status`
# lines are the same answer from the other side, written by the kernel about the process actually
# running, so a flag the daemon accepted and did not apply is visible here rather than assumed.
_CAPABILITY_PROBE = """
import os, pathlib
print('uid', os.getuid())
sealed = pathlib.Path('/tmp/sealed')
sealed.write_text('secret')
sealed.chmod(0)
try:
    sealed.read_text()
except PermissionError:
    print('sealed refused')
else:
    print('sealed read')
for line in pathlib.Path('/proc/self/status').read_text().splitlines():
    field, _, value = line.partition(':')
    if field.startswith('Cap'):
        print(field, value.strip())
"""

# All five capability sets a process carries, in the order `/proc/self/status` prints them, and
# every one of them empty. Spelled out rather than looped over so that a set which stayed full
# names itself in the diff.
_NO_CAPABILITIES = [
    "CapInh 0000000000000000",
    "CapPrm 0000000000000000",
    "CapEff 0000000000000000",
    "CapBnd 0000000000000000",
    "CapAmb 0000000000000000",
]

_NO_NEW_PRIVS_PROBE = """
import pathlib
for line in pathlib.Path('/proc/self/status').read_text().splitlines():
    field, _, value = line.partition(':')
    if field == 'NoNewPrivs':
        print(field, value.strip())
"""


def test_a_trial_holds_no_capabilities(trial: tuple[Path, str], tmp_path: Path) -> None:
    """``--cap-drop=ALL``, asserted as a refusal and as the kernel's own bookkeeping.

    The first line of the expected output is the reason this test is worth its container start.
    The trial runs as **uid 0** - the image sets no ``USER`` and nothing at run time overrides it
    (:mod:`assay.sandbox.container` says why) - so without this flag the sealed file below is
    readable, which is `CAP_DAC_OVERRIDE` doing exactly what it is for. **Measured on this host:**
    with the flag removed from :func:`assay.sandbox.run_in_sandbox` the probe prints
    ``sealed read`` and ``CapPrm 00000000a80425fb``, the daemon's default set.

    ``uid 0`` is asserted rather than merely printed so that a later change that gives the
    container a non-root user has to come back here and to that docstring, instead of leaving
    both saying something that stopped being true.
    """
    workspace, tag = trial

    result = run_in_sandbox(
        image_tag=tag,
        workspace=workspace,
        out_dir=tmp_path,
        argv=(VENV_PYTHON, "-c", _CAPABILITY_PROBE),
        limits=TRIAL_LIMITS,
        timeout_s=_PROBE_BUDGET_S,
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout.split("\n") == ["uid 0", "sealed refused", *_NO_CAPABILITIES, ""]


def test_a_trial_cannot_gain_privileges_it_was_not_given(
    trial: tuple[Path, str], tmp_path: Path
) -> None:
    """``--security-opt=no-new-privileges``, read off the kernel rather than off the argv.

    The bit is what there is to assert: the behaviour it forbids needs a setuid binary in the
    image *and* a caller that would gain something by running one, and a trial that is already
    root gains nothing - the flag is carried for what it denies the moment the container stops
    being root, which is the direction any change to the user is going to go. The bit is not
    vacuous even so: **measured on this host**, without the flag this probe prints
    ``NoNewPrivs 0``, and the kernel then honours a setuid bit inside the image.

    ``no-new-privileges`` and ``no-new-privileges:true`` are both accepted by the daemon here
    (docker 29.7.2, measured); :mod:`assay.sandbox.container` uses the first.
    """
    workspace, tag = trial

    result = run_in_sandbox(
        image_tag=tag,
        workspace=workspace,
        out_dir=tmp_path,
        argv=(VENV_PYTHON, "-c", _NO_NEW_PRIVS_PROBE),
        limits=TRIAL_LIMITS,
        timeout_s=_PROBE_BUDGET_S,
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout == "NoNewPrivs 1\n"
