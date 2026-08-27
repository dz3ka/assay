"""The one place in Assay that starts a process. Everything hostile passes through here.

A mined repository is not a document, it is code: its ``conftest.py``, its build hooks and its
tests all execute as the invoking user (SPEC §5.2). Assay cannot avoid running them - proving
a test red at the parent and green at the commit *is* the product - so it concentrates the
whole exposure in one function that the rest of the package is forbidden to route around.
``tests/host/test_process.py`` asserts that no module outside ``assay.host`` so much as
mentions ``subprocess``, which makes the boundary a grep rather than a habit.

Three properties are load-bearing, and each is spelled out below where it is enforced:

* **No shell, ever.** ``shell=False`` is the default and is never overridden; a ``str`` argv
  is refused at runtime because ``str`` satisfies ``Sequence[str]`` and mypy will not catch it.
* **No ambient environment.** ``env`` is required and explicit. The developer's shell holds
  model API keys, and third-party test code must never be handed them. :func:`minimal_env`
  builds the allowlisted dict so that passing ``os.environ`` takes deliberate effort.
* **Bounded consumption.** Every call carries a timeout, and expiry kills the whole process
  group. A pytest run spawns children; a kill that reaches only the child leaves the half
  that holds the CPU alive, which is exactly what a runaway mined test looks like.
"""

import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from assay.core import AssayError

# Names copied from the ambient environment when :func:`minimal_env` is asked for one. This
# is an allowlist rather than a denylist on purpose: a secret Assay has never heard of is the
# normal case, so anything not named here is dropped by default.
#
# PATH resolves ``git`` and ``uv``. SYSTEMROOT/COMSPEC/PATHEXT are what a Windows process
# needs to start at all (sockets, DLL resolution, executable extensions). TEMP/TMP/TMPDIR
# keep a child's scratch files inside the temp directory the host already accepted.
# HOME/USERPROFILE let git find a user identity rather than aborting a commit for want of one.
_INHERITED_NAMES: Final = (
    "COMSPEC",
    "HOME",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
)

# How long the kill path waits for a signalled group to actually die before escalating, and
# then for its pipes to close. Small: this runs after a timeout has already been spent, and a
# process that ignores its group signal is not going to be talked round by waiting longer.
_KILL_GRACE_S: Final = 0.5
_REAP_TIMEOUT_S: Final = 5.0

# stderr is quoted into the exception message, which a CLI prints as one refusal. A mined
# repo's test run can emit megabytes, so only the tail travels.
_STDERR_EXCERPT_CHARS: Final = 500


class CommandTimeoutError(AssayError):
    """A command outlived its budget and its process group was killed.

    The distinction from :class:`CommandFailedError` is the whole point: a command that
    exited non-zero answered the question, and a command that was killed did not. A mined
    task whose tests hang is discarded and counted, never scored.
    """

    def __init__(self, argv: tuple[str, ...], timeout_s: int) -> None:
        self.argv = argv
        self.timeout_s = timeout_s
        super().__init__(f"command exceeded its {timeout_s}s budget and was killed: {argv[0]}")


class CommandFailedError(AssayError):
    """A command exited non-zero and the caller had asked for that to be an error.

    Raised only under ``check=True``. The default is to return the exit code as data, because
    several of the commands Assay runs (``git apply --check`` above all) use a non-zero exit
    to answer a question rather than to report a fault.
    """

    def __init__(self, result: "CommandResult") -> None:
        self.result = result
        excerpt = result.stderr.strip()[-_STDERR_EXCERPT_CHARS:]
        super().__init__(
            f"command exited {result.exit_code}: {' '.join(result.argv)}"
            + (f"\n{excerpt}" if excerpt else "")
        )


@dataclass(frozen=True)
class CommandResult:
    """What a finished command produced. Frozen: a result is evidence, not a scratch buffer."""

    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str


def minimal_env() -> dict[str, str]:
    """Build the environment a child is allowed to see: :data:`_INHERITED_NAMES` and no more.

    A fresh dict each call, so a caller may add its own tool-specific names (``git.py`` adds
    ``GIT_TERMINAL_PROMPT``) without editing a shared value. The point of the helper is that
    ``run_command(..., env=minimal_env())`` is the short path and ``env=os.environ`` is the
    long one - the secrets on a developer's shell leak by default, not by mistake.
    """
    return {name: os.environ[name] for name in _INHERITED_NAMES if name in os.environ}


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout_s: int,
    env: Mapping[str, str],
    check: bool = False,
) -> CommandResult:
    """Run ``argv`` in ``cwd`` with no shell, exactly ``env``, and a hard time budget.

    Args:
        argv: The executable and its arguments, already split. Never a command string.
        cwd: The working directory; for anything that executes mined code this is a
            throwaway worktree, never the user's clone.
        timeout_s: Wall-clock budget. On expiry the process *group* is killed.
        env: The complete environment for the child. Use :func:`minimal_env`.
        check: Raise :class:`CommandFailedError` on a non-zero exit instead of returning it.

    Raises:
        TypeError: if ``argv`` is a string, which only a shell could interpret.
        ValueError: if ``argv`` is empty.
        CommandTimeoutError: if the budget expired.
        CommandFailedError: if ``check`` and the command exited non-zero.
    """
    if isinstance(argv, str):
        raise TypeError("argv must be a sequence of arguments, not a command string: no shell")
    frozen = tuple(argv)
    if not frozen:
        raise ValueError("argv is empty: there is no command to run")

    # A new group (Windows) or session (POSIX) is what makes the kill below reach the
    # children a test run spawns; it can only be asked for at start time. Written as two
    # literal `sys.platform` branches because that is the form mypy prunes per platform -
    # each name below exists on exactly one of them.
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        new_session = False
    else:
        creation_flags = 0
        new_session = True

    with subprocess.Popen(
        frozen,
        cwd=cwd,
        env=dict(env),
        # No inherited stdin: a mined build hook that asks a question gets EOF and fails,
        # rather than blocking until the timeout with nobody at the keyboard.
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creation_flags,
        start_new_session=new_session,
    ) as process:
        try:
            out, err = process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_group(process)
            raise CommandTimeoutError(frozen, timeout_s) from None
        exit_code = process.wait()

    result = CommandResult(
        argv=frozen,
        exit_code=exit_code,
        stdout=_decode(out),
        stderr=_decode(err),
    )
    if check and result.exit_code != 0:
        raise CommandFailedError(result)
    return result


def _decode(raw: bytes) -> str:
    """Decode child output as UTF-8, replacing anything that is not.

    Bytes rather than ``text=True`` for two reasons: universal-newline translation would
    rewrite a CRLF inside a diff and produce a patch that no longer applies, and a mined repo
    may hold a filename that is not valid UTF-8. Neither is worth crashing a mining run over,
    so undecodable input becomes U+FFFD and the caller reads what it can.
    """
    return raw.decode("utf-8", errors="replace")


def _kill_group(process: "subprocess.Popen[bytes]") -> None:
    """Kill the timed-out process *and its descendants*, then let go of its pipes.

    POSIX: the child leads its own session, so one ``killpg`` reaches every descendant.

    Windows has no process groups that ``TerminateProcess`` respects, and ``Popen.kill()``
    ends the child alone - measured on this host, a grandchild survives it and keeps the
    inherited pipe open, so the reap below would block forever. ``CTRL_BREAK_EVENT`` is what
    ``CREATE_NEW_PROCESS_GROUP`` buys: it is delivered to the whole group. ``kill()`` still
    follows, as the backstop for a child that ignores the break.

    The reap is itself bounded. A descendant that survived both signals still holds the
    inherited pipe, and blocking here would defeat the timeout that got us this far; the
    output of a killed command is not read anyway, since the caller raises.
    """
    if sys.platform == "win32":
        try:
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        except OSError:
            # No console to deliver a control event to (a GUI host, a detached service).
            # Nothing to handle: the unconditional kill below is the fallback.
            pass
        else:
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=_KILL_GRACE_S)
    else:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)

    process.kill()
    with suppress(subprocess.TimeoutExpired):
        process.communicate(timeout=_REAP_TIMEOUT_S)
