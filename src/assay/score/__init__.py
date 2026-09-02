"""Scoring one trial: the executable verdict, and the loop that produces a Result from it.

Tools are ranked on executable signal only (CLAUDE.md, ADR-0003), and this package is where
that rule is code rather than discipline. It has the same two-halved shape as
:mod:`assay.mine`, because it is the same argument: :func:`score_report` is the pure half,
total over every report shape and raising nothing, so the rule that decides a trial can be
exercised on values alone; :func:`run_trial` is the I/O half, driving the ``History``,
``Adapter`` and ``RunnerFactory`` seams and never learning what implements them.

Import these names from ``assay.score``; which submodule holds which is an implementation
detail.
"""

from assay.score.executable import score_report
from assay.score.trial import TrialSetupError, run_trial

__all__ = [
    "TrialSetupError",
    "run_trial",
    "score_report",
]
