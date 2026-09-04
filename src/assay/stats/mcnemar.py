"""The exact McNemar test: whether two tools differ on the tasks they were both given.

Two Wilson bands answer "how uncertain is each tool's own rate", and they answer it about each
tool separately. That is the right question for ranking and the wrong one for comparing, because
the tools were not run on separate suites - they were run on the same tasks, and a task both
tools failed carries no information about which is better. Reading the two independent bands is
therefore reading a paired experiment as an unpaired one, and it throws away the pairing that
makes the comparison cheap.

McNemar reads only the tasks the tools disagreed about: ``b`` that only the first solved, ``c``
that only the second did. Under the null hypothesis that the tools are the same, each of those
``b + c`` tasks was as likely to fall either way, so the split is Binomial(b + c, 1/2) and the
p-value is the probability of a split at least this lopsided.

The distribution is summed exactly, with :func:`math.comb`, rather than approximated by the
chi-square form. The approximation needs an incomplete-gamma CDF - thirty lines of numerics
checkable only against another implementation - and it is invalid below roughly 25 discordant
pairs, which is every suite this harness has mined. The exact sum is four lines and its answers
are hand-computable, which is what every expectation in ``tests/stats/test_mcnemar.py`` is
(ADR-0044).

Pure arithmetic over two integers, like :mod:`assay.stats.wilson`. This module imports nothing
from Assay and nothing that touches a disk, a clock or a socket - see the package docstring -
and in particular it does not know what a task, a tool or a winner is. It returns a probability;
what that probability is allowed to license is decided in the report, where ADR-0005's rule that
only the pass^n intervals may name a winner still holds over it.
"""

from math import comb


def mcnemar_exact_p(only_a: int, only_b: int) -> float:
    """Return the two-sided exact binomial McNemar p for a pair of discordant counts.

    ``only_a`` is the number of tasks the first tool solved and the second did not, ``only_b``
    the reverse. Tasks both tools solved and tasks neither solved are not arguments, because the
    test does not read them: they are the concordant pairs, and they cancel.

    Over ``n = only_a + only_b`` discordant tasks with ``m = min(only_a, only_b)``::

        p = min(1, 2 * sum(comb(n, i) for i in range(m + 1)) / 2**n)

    The doubling is the second tail, not a correction. The outcomes at least as lopsided as the
    one observed are ``{X <= m}`` together with ``{X >= n - m}``, and the null distribution is
    symmetric, so the two have the same weight. They are disjoint whenever ``m < n - m``; the one
    case where they are not is ``only_a == only_b``, an exactly even split, where their union is
    every outcome there is. ``min`` is what states that: the p is 1, because nothing about the
    observed split was unusual. Zero discordant tasks is the degenerate member of that family
    and returns 1.0 for the same reason - the tools solved the same tasks, and a test given
    nothing to distinguish them must not report evidence that they differ.

    The division is left between two integers so CPython rounds it once, correctly, at the end;
    the numerators here are small, but a float in the middle of an exact sum is how an exact test
    stops being one.

    Raises:
        ValueError: if either count is negative. A negative number of tasks is a pairing that
            has already gone wrong upstream, and a p derived from it would be a number nobody
            measured.
    """
    if only_a < 0 or only_b < 0:
        raise ValueError(
            f"a discordant task count cannot be negative, got only_a={only_a} and only_b={only_b}"
        )

    discordant = only_a + only_b
    smaller = min(only_a, only_b)
    # Annotated because `int ** int` is `Any` to mypy - a negative exponent would make it a
    # float - and an exact sum must not pick up an unchecked type on its way to one division.
    outcomes: int = 2**discordant
    tail = sum(comb(discordant, split) for split in range(smaller + 1))
    return min(1.0, 2 * tail / outcomes)
