"""The percentile bootstrap of a mean: the band for a score that is not a proportion.

Wilson answers "how uncertain is this fraction of successes", and pass^n is exactly that shape -
each task either passed every trial or did not. pass@1 is not. It is the mean over tasks of each
task's own pass rate (SPEC 4, and ADR-0035 for why that denominator is tasks), so there is no
numerator and no denominator for a proportion interval to be an interval *of*, and pooling the
trials to manufacture one would report a band around a different number than the one printed
beside it. What that mean has instead is a sample of per-task rates, and the uncertainty worth
reporting is the uncertainty of the tasks: another suite mined from the same repository would
have drawn a different handful of them.

Resampling the tasks with replacement is the estimate of that. Each resample is a suite the
miner might have produced, its mean is the pass@1 that suite would have reported, and the
interval is the middle ``level`` of those means read off directly - the percentile method, no
distributional assumption, no standard error, and no normal approximation anywhere near it
(CLAUDE.md bans it for proportions, and it would be no better here).

Pure arithmetic over a sequence of floats. Like :mod:`assay.stats.wilson` this module imports
nothing from Assay and nothing that touches a disk, a clock or a socket - see the package
docstring - and it never learns that its values are pass rates, which is what keeps the decision
about what counts as a success in the one function that is allowed to make it.
"""

from collections.abc import Sequence
from math import ceil, floor
from random import Random

# The two-sided level Assay reports at, spelled as the fraction rather than as the tail, because
# that is how a report names it. The twin of :data:`assay.stats.wilson.Z_95`, and the same 95%.
LEVEL_95: float = 0.95


def bootstrap_mean_interval(
    values: Sequence[float], *, resamples: int, seed: int, level: float = LEVEL_95
) -> tuple[float, float]:
    """Return the percentile bootstrap interval for the mean of ``values``.

    ``resamples`` samples of ``len(values)`` values are drawn with replacement, their means are
    sorted, and the endpoints are the order statistics at ``tail = (1 - level) / 2``::

        low  = sorted_means[floor(tail * resamples)]
        high = sorted_means[ceil((1 - tail) * resamples) - 1]

    Both endpoints are means that were actually observed, so the band cannot leave the range of
    the values and needs no clamp: this function does not know that its inputs are rates, and a
    caller whose numbers live somewhere other than [0, 1] gets a band in its own units.

    Indices are drawn as ``int(rng.random() * n)``. ``random()`` is the one draw CPython
    documents as reproducible for a given seed across versions; ``choice``, ``choices``,
    ``randrange`` and ``sample`` are not, and a band that moved under a Python upgrade would
    make a published report unreproducible, which SPEC 5.5 does not allow. The generator is
    built here from ``seed`` rather than taken as an argument or read from the ``random``
    module's shared state, so nothing a caller did earlier can move this band.

    ``seed`` and ``resamples`` are required and have no defaults, deliberately. They are the two
    inputs that decide which band gets printed, and a leaf that imports nothing from Assay has
    no standing to set that policy - the report that spends them is the module that names them,
    and it names them as constants rather than as anything a run can vary.

    Raises:
        ValueError: if ``values`` is empty, if ``resamples`` is not positive, or if ``level``
            does not lie strictly between 0 and 1. Each one means the caller is asking for a
            band that has no sample, no resamples to take a percentile of, or no percentile to
            take - and any answer to those would be a number nobody measured.
    """
    if not values:
        raise ValueError("a bootstrap band needs at least one value, got an empty sequence")
    if resamples <= 0:
        raise ValueError(f"a bootstrap band needs at least one resample, got resamples={resamples}")
    if not 0.0 < level < 1.0:
        raise ValueError(
            f"level={level} is not a confidence level; it must lie strictly between 0 and 1"
        )

    size = len(values)
    rng = Random(seed)
    means = sorted(
        sum(values[int(rng.random() * size)] for _ in range(size)) / size for _ in range(resamples)
    )

    tail = (1.0 - level) / 2.0
    return means[floor(tail * resamples)], means[ceil((1.0 - tail) * resamples) - 1]
