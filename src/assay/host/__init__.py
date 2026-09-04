"""The audited seam: every process Assay starts, and every git question it asks, live here.

A mined repository is code Assay is obliged to execute (SPEC §5.2), so the exposure is worth
concentrating rather than spreading. ``host`` is the only package allowed to import
``subprocess``; ``tests/host/test_process.py`` asserts that no other module in ``src/assay``
even mentions the name, which turns "we are careful about subprocesses" into a grep.

Import these names from ``assay.host`` rather than from the submodules; the split between
``process`` (the one call site) and ``git`` (the one caller of that call site in M1) is an
implementation detail, this surface is not.

From M3 the package holds a second audited seam, on the same terms: :mod:`assay.host.model_api`
is the only module in ``src/assay`` that may open a socket, and ``tests/host/test_network_egress``
asserts that no other module - inside this package or out of it - imports ``socket``, ``ssl``,
``urllib`` or an HTTP client (ADR-0036). The exemption is that one module path rather than this
directory, because ``git.py``'s standing claim is that it never clones and never fetches.

Nothing here is pure, with one deliberate exception: :mod:`assay.host.junit` starts nothing
and opens nothing, and lives here rather than above the seam because what it reads is a
report only a run on this side produces - by :class:`PytestHostRunner` in M1, and by a run
inside the sandbox from M2. It is not exported: its caller is a module, not a milestone.

Everything *above* the seam - the miner, the validator, the scorer - is pure, and takes an
instance of the ``History`` protocol :class:`GitHistory` satisfies (CLAUDE.md).
"""

from assay.host.git import CheckoutState, GitError, GitHistory, checkout_state
from assay.host.model_api import HttpModelTransport
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
    "HttpModelTransport",
    "PytestHostRunner",
    "SelectorError",
    "checkout_state",
    "minimal_env",
    "provision_venv",
    "run_command",
]
