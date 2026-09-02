"""The error every deliberate refusal in this package raises.

A module of its own, which is the placement rule in :mod:`assay.core.errors` ("an error lives
in the module that raises it") read as closely as two raisers allow: both
:mod:`assay.sandbox.image` and :mod:`assay.sandbox.runner` refuse values, and putting the class
in either would make the other import a sibling module for its exception alone.

Why an :class:`~assay.core.AssayError` and not the ``ValueError`` these refusals were: the base
class is how :mod:`assay.cli` ends a command on one sentence rather than a traceback - ``mine``
and ``validate`` each wrap their walk in ``except (AssayError, OSError)`` - and it is what lets
a failure be a *recorded* outcome instead of an ended run where a caller genuinely records one.
Exactly one does: ``assay.host.provision_venv``'s failure is caught at the host seam in
``assay.cli.host_runner_for`` and counted ``unprovisioned``, so a commit that cannot be given an
environment costs a row rather than the walk. That catch is at the seam, not in the miner.

No walk reaches the refusals below, because :func:`assay.mine.pytest_selectors` decides which of
a commit's changed test files a runner can be pointed at first, on the task's own data (ADR-0029:
a selector no runner would accept is decided in the miner, never caught at the seam). The one
caller left that can be handed a value this module refuses is :func:`assay.score.run_trial`,
which builds its selection from a task's recorded node ids, and there the refusal still ends that
scoring run - a residue ADR-0029 names deliberately rather than a gap.
"""

from assay.core import AssayError


class SandboxError(AssayError):
    """Assay refused to build or run a container with a value it was handed.

    A cutoff that is not the canonical instant, an extras clause that is empty or not
    allowlisted, a selector that would be read as a command-line option. Every one of them is
    on its way into a shell line, an argv or a content address, and every one is refused rather
    than repaired: a value Assay quietly fixed would build or measure something nobody chose.
    """
