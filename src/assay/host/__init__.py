"""The audited seam: every process Assay starts, and every git question it asks, live here.

A mined repository is code Assay is obliged to execute (SPEC §5.2), so the exposure is worth
concentrating rather than spreading. ``host`` is the only package allowed to import
``subprocess``; ``tests/host/test_process.py`` asserts that no other module in ``src/assay``
even mentions the name, which turns "we are careful about subprocesses" into a grep.

Import these names from ``assay.host`` rather than from the submodules; the split between
``process`` (the one call site) and ``git`` (the one caller of that call site in M1) is an
implementation detail, this surface is not.

Nothing here is pure, with one deliberate exception: :mod:`assay.host.junit` starts nothing
and opens nothing, and lives here rather than above the seam because what it reads is a
report only a run on this side produces - by :class:`PytestHostRunner` in M1, and by a run
inside the sandbox from M2. It is not exported: its caller is a module, not a milestone.

Everything *above* the seam - the miner, the validator, the scorer - is pure, and takes an
instance of the ``History`` protocol :class:`GitHistory` satisfies (CLAUDE.md).
"""

from assay.host.git import CheckoutState, GitError, GitHistory, checkout_state
from assay.host.process import (
    CommandFailedError,
    CommandResult,
    CommandTimeoutError,
    minimal_env,
    run_command,
)
from assay.host.pytest_runner import PytestHostRunner, SelectorError
from assay.host.venv import EnvironmentSetupError, provision_venv

__all__ = [
    "CheckoutState",
    "CommandFailedError",
    "CommandResult",
    "CommandTimeoutError",
    "EnvironmentSetupError",
    "GitError",
    "GitHistory",
    "PytestHostRunner",
    "SelectorError",
    "checkout_state",
    "minimal_env",
    "provision_venv",
    "run_command",
]
