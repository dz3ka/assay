"""The statistics Assay is allowed to publish, and nothing that knows what they describe.

``stats`` imports nothing from Assay. Not ``core``, not ``report``, not ``results`` - the
dependency runs one way only, and this package is a leaf like :mod:`assay.core` is a root. A
band around a proportion is arithmetic over two integers; the moment it could reach a result
set it would be tempting to hand it one and let it decide what the numerator was, which is how
a statistic starts encoding a policy. Deciding what counts as a success is
:func:`assay.report.summarise`'s job, and it is the only caller that knows.

Two bands, because a report carries two scores of different shapes. pass^n is a proportion over
tasks and gets :func:`wilson_interval`; the normal approximation is banned by CLAUDE.md's
measurement rules and no function here offers it. pass@1 is a mean of per-task rates rather than
a proportion, so it gets :func:`bootstrap_mean_interval` instead - a different instrument, named
in the report beside the number, never the same one stretched to cover both.

One test, which is not a band at all. A report also compares two tools, and the two bands are
the wrong instrument for that: the tools were run on the same tasks, so the comparison is paired
and the tasks they both passed or both failed carry nothing. :func:`mcnemar_exact_p` reads the
tasks they disagreed about and returns the probability of a split that lopsided if the tools
were the same - two integers again, and again no idea what they count. Whether a small p may
name a winner is not its question: it may not, and the rule stays where it already lives
(ADR-0005, ADR-0044).

Import these names from ``assay.stats`` rather than from the submodules.
"""

from assay.stats.bootstrap import LEVEL_95, bootstrap_mean_interval
from assay.stats.mcnemar import mcnemar_exact_p
from assay.stats.wilson import Z_95, wilson_interval

__all__ = [
    "LEVEL_95",
    "Z_95",
    "bootstrap_mean_interval",
    "mcnemar_exact_p",
    "wilson_interval",
]
