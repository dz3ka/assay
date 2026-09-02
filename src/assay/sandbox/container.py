"""The policy a trial runs under: one function, and no second way to start a container.

SPEC §5.2 and §5.3 are two sentences - model-generated code runs in a container, and a trial has
no network - and both are only as true as the *worst* place in the tree that starts a container.
So there is exactly one such place, and every caller goes through it, tests included. That is
what makes ``tests/sandbox/test_container_policy.py`` evidence rather than decoration: it proves
"no network" about the argv a real trial takes, not about an argv a test wrote to resemble one.

Every flag below is a trust property spelled as a command-line argument:

* ``--network none`` - no interface at all, not a filtered one. Dependencies are installed when
  the image is built (:mod:`assay.sandbox.image`), so a trial that wants to reach the index has
  nothing to reach it with. M3's allowlisted model endpoint is the adapter's business and stays
  outside this container; a trial that could open a socket could also ``pip install`` its way to
  a passing test, and one will.
* ``--pull never`` - a tag that is not on this host is refused here rather than fetched. The
  task image is built locally and never pushed anywhere (:mod:`assay.sandbox.image`), because
  an image holding the repository *is* the repository, so an absent tag means something on this
  host removed it - ``docker image prune`` between mining and running - and the honest answer is
  to fail. Under the default policy the client instead asks a registry for a repository that
  exists nowhere but here: measured, ``Unable to find image ... locally`` followed seconds later
  by ``pull access denied``, which is a network round trip taken from inside the trial path and
  therefore the one thing SPEC §5.1 does not allow. The refusal arrives as exit 125, and
  :func:`assay.score.score_report` reads that as ``ERRORED`` rather than as the tool's failure.
* ``--read-only`` plus the workspace mounted ``:ro`` - the filesystem a trial may change is
  ``/out`` and its own ``/tmp``, and nothing else. The workspace is what the trial's work is
  measured against by ``git diff``, so a trial that could edit it in place could edit the
  measurement. It writes its patch to ``/out`` instead, and the host applies it.
* ``--memory``/``--memory-swap``/``--cpus``/``--pids-limit`` - the ceiling from
  :class:`~assay.sandbox.ContainerLimits`, which the caller chooses. ``--memory-swap`` is set
  equal to ``--memory`` so that a host *with* swap kills the container instead of letting it
  page for minutes; on this WSL2 host the VM has no swap, so the flag cannot be shown to be
  load-bearing here (measured, see :mod:`assay.sandbox.image`) and is carried for the hosts
  where it is.
* ``--cap-drop=ALL`` plus ``--security-opt=no-new-privileges`` - the two flags that matter
  because the trial runs as root (below). The daemon's default set is not empty, and **measured
  on this host** it is ``CapEff 00000000a80425fb``: with it a trial sealed a file of its own at
  mode ``000`` and read it straight back, which is ``CAP_DAC_OVERRIDE``, the capability by which
  uid 0 ignores the permissions on every file it can reach - the mounted workspace included.
  Dropped, the same read is refused. ``no-new-privileges`` is what stops the drop from being
  undone: without it the kernel still honours a setuid bit inside the image across ``execve``,
  so a privilege denied here could be picked back up one exec later.
* ``HOME=/tmp`` - the root filesystem is read only and ``/root`` is on it, so a tool that writes
  a dotfile at start-up would otherwise die before running a test, for a reason having nothing
  to do with the task.

The trial runs as **uid 0**, and that is the largest thing the list above does not fix. No
``USER`` is set: the image installs the project editable into ``/opt/venv`` as root
(:mod:`assay.sandbox.image`), and ``/out`` is a bind mount of a directory the *host* process
owns. **Measured on this host**, the same image run with ``--user 1000:1000`` cannot write
``/out`` at all - ``EACCES`` on the first write - and ``/out`` is a trial's only way to hand back
a junit report, so a non-root trial is a change to how ``/out`` is created rather than one more
flag. What the two flags buy against a root process is real and bounded: uid 0 holding no
capabilities can no longer read past a file mode, chown, ``mknod``, or open a raw socket, and
cannot regain any of it through a setuid binary. What they do not buy is anything that being uid
0 already permits on the mounts it *is* given, or any part of the kernel surface - the daemon's
default seccomp profile is the only thing between a trial and a kernel bug, and neither flag
narrows it.

The wall-clock ceiling needs the container's name, and that is the whole reason for ``--name``.
:func:`assay.host.run_command` kills the *client* when a budget expires, and the docker CLI is a
remote control rather than a parent process, so that need not end the container. So a timed-out
run is followed by ``docker kill``, and only then does ``CommandTimeoutError`` continue on its
way to the runner, which reports it as a test report with ``timed_out`` set.

How much that kill buys depends on the host, and honestly: **measured on Windows**, ending the
client's console group already takes the container with it, so removing the kill leaves
``tests/sandbox/test_container_policy.py`` green. *unverified:* on POSIX the group is ended with
``SIGKILL``, which no client can catch or forward, and there the kill is the only thing that
stops a trial outliving its own budget. It is carried for that host.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Final
from uuid import uuid4

from assay.host import CommandResult, CommandTimeoutError, minimal_env, run_command
from assay.sandbox.image import WORKSPACE_DIR
from assay.sandbox.models import ContainerLimits

# Where a trial writes what it produces: its junit report, and from M3 the patch it wants
# scored. The one writable bind mount, and the only path in the container whose contents the
# host reads afterwards.
OUT_DIR: Final = "/out"

# Scratch space that is not a bind mount. A tmpfs rather than a writable layer because
# ``--read-only`` has already refused the layer, and because scratch that dies with the
# container is scratch nobody has to clean up.
_TMP_DIR: Final = "/tmp"

# The budget for the kill that follows a timeout. Short on purpose: this runs after a trial has
# already spent its whole budget, and a daemon that cannot accept one more request in this long
# is wedged rather than busy.
_KILL_TIMEOUT_S: Final = 60


def run_in_sandbox(
    *,
    image_tag: str,
    workspace: Path,
    out_dir: Path,
    argv: Sequence[str],
    limits: ContainerLimits,
    timeout_s: int,
) -> CommandResult:
    """Run ``argv`` inside ``image_tag`` under the whole trial policy, and return what it did.

    Args:
        image_tag: The task image, from :func:`assay.sandbox.build_task_image`.
        workspace: The checkout to mount read-only at :data:`assay.sandbox.WORKSPACE_DIR`. The
            image installed the project *editable* against that path at build time, so the code
            the trial imports is this tree rather than a copy frozen into a layer.
        out_dir: A host directory to mount writable at :data:`OUT_DIR`. Must exist: it is also
            the client's working directory, and a trial's only way to hand anything back.
        argv: The command inside the container, already split. Absolute paths, since nothing
            here relies on the image's ``PATH`` - :data:`assay.sandbox.VENV_PYTHON` is the
            interpreter the environment was built around.
        limits: The resource ceiling. No defaults anywhere in this package, deliberately: see
            :class:`assay.sandbox.ContainerLimits`.
        timeout_s: Wall-clock budget for the whole container. On expiry the container is killed
            and :class:`assay.host.CommandTimeoutError` is raised.

    Returns:
        The client's result, exit code included and uninterpreted. Uninterpreted rather than
        harmless: ``docker run`` reports the command's own status *only when the command ran*,
        and answers with codes of its own when it did not - 125 when the client or the daemon
        failed (an absent image tag, above all, which ``--pull never`` makes fail locally), and
        126 or 127 when the command could not be invoked. Which codes are a verdict and which
        are a fault is a question about the argv, and this function runs whatever argv it is
        handed: ``tests/sandbox/test_container_policy.py`` reads a raw 137 from the OOM killer
        through it and calls that a success. So the reading is left to the caller that knows
        what it ran - :func:`assay.score.score_report` scores anything outside pytest's own 0-5
        band as ``Outcome.ERRORED``, which is where a docker failure stops being a tool's
        ``FAILED``. The one carve-out is the 137 above: a cgroup kill is a measured,
        tool-attributable outcome rather than an ambiguous client failure, so it scores
        ``FAILED`` (ADR-0028).

    Raises:
        CommandTimeoutError: if the budget expired. The container is killed first; if that kill
            itself times out the daemon is wedged, and the error that reports so is allowed to
            replace this one - both are the truth, and the original stays on the exception's
            context chain.
    """
    # Unique per container: trials of one suite run one after another today, but a name that
    # collided would have the timeout kill someone else's container, which is the kind of bug a
    # harness cannot have. Prefixed so that a leaked container names its origin in `docker ps`.
    name = f"assay-trial-{uuid4()}"
    command = (
        "docker",
        "run",
        # The daemon removes the container once it stops, killed or not. A trial per task per
        # tool per repetition is thousands of containers a run, and every one of them holds a
        # copy of the workspace's writable layer until something reaps it.
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        # The other half of "a trial reaches no network": without this, an image tag missing
        # from this host sends the *client* to a registry, on the trial's own path.
        "--pull",
        "never",
        "--read-only",
        # Untrusted code, so the trial gets the empty capability set rather than the daemon's
        # default one, and cannot pick a privilege back up through a setuid binary either.
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        # POSIX spelling of the host paths: a Windows `C:\\...` is what `str()` gives and
        # `C:/...` is what the daemon was measured to accept, drive letter and all.
        "--volume",
        f"{workspace.as_posix()}:{WORKSPACE_DIR}:ro",
        "--volume",
        f"{out_dir.as_posix()}:{OUT_DIR}",
        "--tmpfs",
        _TMP_DIR,
        "--env",
        f"HOME={_TMP_DIR}",
        "--memory",
        f"{limits.memory_mb}m",
        "--memory-swap",
        f"{limits.memory_mb}m",
        "--cpus",
        limits.cpus,
        "--pids-limit",
        str(limits.pids),
        image_tag,
        *argv,
    )
    try:
        return run_command(
            command,
            # The output directory, not the workspace: the client writes nothing into its
            # working directory, but the tree a trial is about to be scored against is not the
            # place to find that out.
            cwd=out_dir,
            timeout_s=timeout_s,
            env=minimal_env(),
        )
    except CommandTimeoutError:
        # Only on this path. A container that exited on its own needs no killing, and an
        # unconditional kill would charge every trial in every run for a docker round trip that
        # can only report "no such container".
        _kill_container(name, cwd=out_dir)
        raise


def _kill_container(name: str, *, cwd: Path) -> None:
    """Stop the container ``name``, best effort - it may already have gone.

    Never checked: the container this is aimed at was killed on the far side of a budget nobody
    is waiting on any more, and "no such container" is a perfectly good outcome. What is not
    swallowed is the daemon failing to answer at all, which raises from inside the ``except``
    that called this and so reaches the caller with the original timeout as its context.
    """
    run_command(
        ("docker", "kill", name),
        cwd=cwd,
        timeout_s=_KILL_TIMEOUT_S,
        env=minimal_env(),
    )
