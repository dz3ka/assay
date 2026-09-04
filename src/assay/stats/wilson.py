"""The Wilson score interval: the only band Assay ever puts around a proportion.

Never the normal approximation (CLAUDE.md). ``p +/- z*sqrt(p(1-p)/n)`` collapses to a
zero-width interval at ``k = 0`` and at ``k = n`` - the two results this harness produces most
often, since the null adapter fails everything and the ground-truth oracle passes everything -
and it can also reach outside [0, 1], which is not a wider claim but an unrenderable one. The
Wilson interval is the same confidence statement solved for ``p`` instead of approximated at
``p-hat``, so it stays inside the unit interval and keeps width where the evidence is thin.

Pure arithmetic over two integers. This module imports nothing from Assay and nothing that
touches a disk, a clock or a socket - see the package docstring for why that matters.
"""

from math import sqrt

# The standard normal deviate for a two-sided 95% interval, to the precision a float holds.
# Spelled out rather than computed: importing an inverse-normal implementation to obtain one
# constant would make the whole distribution a dependency of a number that never changes, and
# a reader can check this one against any table.
Z_95: float = 1.959963984540054


def wilson_interval(successes: int, trials: int, *, z: float = Z_95) -> tuple[float, float]:
    """Return the closed Wilson score interval for ``successes`` out of ``trials``.

    The band around ``k/n`` at ``z`` standard normal deviates::

        centre = (k + z^2/2) / (n + z^2)
        half   = z / (n + z^2) * sqrt(k(n - k)/n + z^2/4)

    and the result is ``(centre - half, centre + half)`` clamped to [0, 1]. The clamp is
    arithmetic hygiene, not a correction: the exact endpoints already lie inside the unit
    interval, and clamping keeps a last-bit rounding error at ``k = 0`` or ``k = n`` from
    producing a band the report's schema would refuse.

    ``z`` is a keyword argument rather than a hard-coded 95% so that a caller reporting a
    different level does not need a second function; every caller in Assay today takes the
    default, and the level a report was computed at is stated in the report.

    Raises:
        ValueError: if ``trials`` is not positive, or ``successes`` is not in ``[0, trials]``.
            Both mean the caller's own counting is wrong - a summary over no results, or more
            passes than attempts - and a band derived from either would be a number nobody
            measured.
    """
    if trials <= 0:
        raise ValueError(f"an interval needs at least one trial, got trials={trials}")
    if not 0 <= successes <= trials:
        raise ValueError(
            f"successes={successes} is not a count of {trials} trials; "
            "it must be between 0 and the number of trials"
        )

    z_squared = z * z
    denominator = trials + z_squared
    centre = (successes + z_squared / 2) / denominator
    half_width = z / denominator * sqrt(successes * (trials - successes) / trials + z_squared / 4)
    return max(0.0, centre - half_width), min(1.0, centre + half_width)
