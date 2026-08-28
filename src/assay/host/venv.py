"""The environment a mined repository's tests are run in, built before anything is run.

Assay never runs a target repository's tests against its own interpreter: the repository under
evaluation pins its own dependencies, and importing them into the process that is measuring
them would make the measurement a property of Assay's lockfile (SPEC §5.2, CLAUDE.md
"dependencies are installed when the task image is built, not during the trial"). So each
workspace gets its own ``uv`` virtual environment, and :class:`assay.host.PytestHostRunner`
is handed the interpreter inside it rather than :data:`sys.executable`.

The environment lives at ``<workspace>/.venv``, which is where ``uv venv`` puts it and what
every repository's ``.gitignore`` already expects. It is untracked, so the ``git diff`` that
scores a trial never sees it - the same property ``-p no:cacheprovider`` buys in the runner,
by a different route.

**Measured, 2026-08-27** (uv 0.12.5, CPython 3.12.10, Windows dev host, one-file package
whose only dependency is pytest), because the plan for M1 carried this as an open assumption:

* ``uv venv``: 0.03-0.34 s, no network. It links an interpreter already on the machine.
* ``uv pip install -e . pytest``: 4.2 s cold-ish, 1.6-1.8 s with uv's cache warm, 2.8 s with
  ``--no-cache`` against the live index.
* Network is *not* required once uv's cache holds the wheels: ``--offline`` installed the same
  three distributions in 1.8 s. With ``--offline --no-cache`` it fails outright, exit 1,
  "Packages were unavailable because the network was disabled".

The consequence for a by-hand run over a real repository: provisioning is seconds, not
minutes, but only the *second* run is offline-safe. A first run on a machine whose uv cache
has never seen the target's dependencies needs the network, and a large dependency tree
(httpie's, say) pays its download once. The budget is the caller's argument for that reason:
there is no single number that is both honest about a cold cache and tight on a warm one.
"""

import sys
from pathlib import Path
from time import monotonic
from typing import Final

from assay.core import AssayError
from assay.host.process import minimal_env, run_command

# Where ``uv venv`` places an environment when it is not told otherwise, spelled out because
# the interpreter path below is built from it rather than parsed out of uv's output.
_VENV_DIRECTORY: Final = ".venv"

# Installed on top of the project itself. A repository declares pytest as a *development*
# dependency or not at all, so ``-e .`` alone routinely produces an environment in which
# ``python -m pytest`` does not exist - and a run that cannot start is evidence of nothing.
_TEST_RUNNER_REQUIREMENT: Final = "pytest"


class EnvironmentSetupError(AssayError):
    """The workspace could not be given an environment its tests could run in.

    Not a countable *rejection*: nothing about the commit's own red->green behaviour has been
    observed, so filing it under one of the seven ``GateRejection`` reasons would falsify the
    yield line. It is not a reason to abandon the run either, which an earlier version of this
    docstring claimed - provisioning happens once **per commit**, so a repository mined back
    past the commit that introduced its packaging has commits that simply cannot be installed,
    and a walk that died on the first of them would report no yield at all.

    The caller that wires this into the miner catches it and hands ``None`` back through
    :data:`assay.mine.protocols.RunnerFactory`; the commit is then counted as
    ``MiningYield.unprovisioned``, examined but never a candidate.
    """


def provision_venv(workspace: Path, *, timeout_s: int) -> Path:
    """Create ``<workspace>/.venv``, install the project into it, return its interpreter.

    Args:
        workspace: A checked-out worktree holding the project to install. Never the user's
            clone - provisioning writes into this directory.
        timeout_s: Wall-clock budget for *both* uv invocations together. The second is given
            what the first did not spend, so a caller's ceiling is a ceiling rather than a
            per-command allowance that can be paid twice.

    Returns:
        The path to the environment's ``python`` executable, ready to be handed to
        :class:`assay.host.PytestHostRunner`.

    Raises:
        EnvironmentSetupError: if either uv command failed or ran out of budget, or if uv
            reported success without leaving an interpreter where one was expected.
    """
    deadline = monotonic() + timeout_s
    _uv(workspace, "venv", timeout_s=_remaining(deadline))
    python = _interpreter(workspace)
    # ``--python`` explicitly rather than letting uv discover ``.venv``: the child's
    # environment is the allowlist from :func:`minimal_env`, which carries no ``VIRTUAL_ENV``,
    # and an install that silently chose a different interpreter would be found much later,
    # as a missing import inside a mined test run.
    _uv(
        workspace,
        "pip",
        "install",
        "--python",
        str(python),
        "-e",
        ".",
        _TEST_RUNNER_REQUIREMENT,
        timeout_s=_remaining(deadline),
    )
    if not python.exists():
        raise EnvironmentSetupError(f"uv reported success but left no interpreter at {python}")
    return python


def _uv(workspace: Path, *arguments: str, timeout_s: int) -> None:
    """Run one uv command in ``workspace``, translating any failure into this module's error."""
    try:
        run_command(
            ("uv", *arguments),
            cwd=workspace,
            timeout_s=timeout_s,
            env=minimal_env(),
            check=True,
        )
    except AssayError as failure:
        raise EnvironmentSetupError(str(failure)) from failure


def _interpreter(workspace: Path) -> Path:
    """Where the environment's interpreter lands, which is the one thing that is per-platform.

    Two literal ``sys.platform`` branches, the form ``mypy --strict`` prunes per platform, for
    the same reason :mod:`assay.host.process` uses it: a suite is mined on Windows and
    replayed on Linux, and only one of these two lines is ever the truth on a given host.
    """
    if sys.platform == "win32":
        return workspace / _VENV_DIRECTORY / "Scripts" / "python.exe"
    return workspace / _VENV_DIRECTORY / "bin" / "python"


def _remaining(deadline: float) -> int:
    """Seconds left before ``deadline``, never below one.

    A floor rather than a zero: ``run_command`` treats its timeout as a real budget, and
    handing it zero would kill a command that had not been given the chance to start.
    """
    return max(1, int(deadline - monotonic()))
