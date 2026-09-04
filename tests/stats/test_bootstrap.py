"""The second arithmetic in Assay that nobody may check against itself.

A resampled band has one obvious wrong test: draw the resamples again here and compare. That
would agree with any implementation, including one that draws indices with ``rng.choice`` and
therefore prints a different band on a future CPython - which is the whole failure the draw
contract exists to prevent. So every expected value below is either worked out from the
distribution of the resample mean before any code ran (CLAUDE.md: hand-computed known values,
never the function itself), or is the single pinned band at the bottom, which is measured rather
than derived and labelled as such.

The estimator, for ``n`` values resampled ``R`` times at level ``L``:

    each resample draws n indices as int(rng.random() * n) and records the mean of the values
    they name, tail = (1 - L) / 2, and the band is

        low  = sorted_means[floor(tail * R)]
        high = sorted_means[ceil((1 - tail) * R) - 1]

Both endpoints are order statistics - no interpolation, no clamp - so each one is a mean that
was actually observed. That is what makes the cases below hand-computable: the mean of a
resample of ``[0, 0, 0, 1]`` is ``k/4`` where ``k`` is the number of draws that hit the 1, and
``k`` is binomial with four trials at probability 1/4. The band is then whichever cell of that
distribution the two order statistics land in, and the cells are far enough from the boundary
that the arithmetic settles it without running anything.

Every value here is dyadic - halves, quarters, eighths - so that a resample mean is exact in
binary floating point and the literals can be compared with ``==`` rather than to a tolerance.
That is a property of the fixtures, not of the function.
"""

import pytest

from assay.stats import LEVEL_95, bootstrap_mean_interval

# A resample count large enough that the two cases with a computed order statistic sit about
# seven standard errors from the cell boundary they must not cross. They are hand-computed
# claims about a distribution, so they hold for any seed; the seed is fixed only because the
# function refuses to invent one.
_RESAMPLES = 4000


def test_one_value_gives_a_band_of_zero_width() -> None:
    # n=1: int(rng.random() * 1) is 0 for every draw, since random() lives in [0, 1). Every
    # resample is therefore the same single value and every order statistic is that value.
    # A one-task suite has no spread to measure, and the band says so instead of inventing one.
    assert bootstrap_mean_interval((0.42,), resamples=1000, seed=1) == (0.42, 0.42)


def test_identical_values_give_a_band_of_zero_width() -> None:
    # Four tasks that all scored 0.25: whichever indices are drawn, the resample mean is
    # 0.25 exactly (0.25 is dyadic, so the four-term sum and the division are both exact).
    # The degenerate case is worth pinning because it is the one a resampler gets wrong by
    # accident - an off-by-one in the index arithmetic shows up here as an IndexError.
    assert bootstrap_mean_interval((0.25, 0.25, 0.25, 0.25), resamples=1000, seed=2) == (
        0.25,
        0.25,
    )


def test_two_opposite_tasks_cannot_rule_out_either_end() -> None:
    # n=2 over {0, 1}: a resample mean is 0 only when both draws hit the 0 (probability 1/4)
    # and 1 only when both hit the 1 (also 1/4). Both tails are 0.25, which is ten times the
    # 0.025 an endpoint would have to reach past, so the 2.5th percentile is 0 and the 97.5th
    # is 1. Two tasks buy no information at all, and the widest band in the unit interval is
    # the honest reading of that.
    assert bootstrap_mean_interval((0.0, 1.0), resamples=1000, seed=3) == (0.0, 1.0)


def test_the_upper_end_is_the_cell_the_order_statistic_lands_in() -> None:
    # n=4 over {0, 0, 0, 1}: a resample mean is k/4 for k draws that hit the 1, and k is
    # binomial(4, 1/4), so in 256ths the cells are
    #   P(k=0) = 3^4      = 81      P(k=1) = 4*3^3 = 108     P(k=2) = 6*3^2 = 54
    #   P(k=3) = 4*3      = 12      P(k=4)         = 1
    # Cumulatively: 81/256 = 0.3164, 189/256 = 0.7383, 243/256 = 0.9492, 255/256 = 0.9961.
    # The lower endpoint is the 2.5th percentile, and 0.3164 already covers it, so it is 0.0.
    # The upper is the 97.5th: 0.9492 falls short and 0.9961 clears it, so the 97.5th
    # percentile sits in the k=3 cell and the endpoint is 0.75 - not 1.0, which needs all four
    # draws to hit the single passing task and happens once in 256 resamples.
    assert bootstrap_mean_interval((0.0, 0.0, 0.0, 1.0), resamples=_RESAMPLES, seed=4) == (
        0.0,
        0.75,
    )


def test_the_lower_end_is_the_cell_the_order_statistic_lands_in() -> None:
    # The same computation read from the other end: n=4 over {0, 1, 1, 1}, so a resample mean
    # is j/4 for j draws that miss the 0, and j is binomial(4, 3/4). In 256ths the low cells
    # are P(j=0) = 1 and P(j=1) = 4*3 = 12, cumulating to 1/256 = 0.0039 and 13/256 = 0.0508.
    # The 2.5th percentile therefore lands in the j=1 cell and the lower endpoint is 0.25.
    # The upper endpoint is 1.0, because P(j=4) = 81/256 = 0.3164 covers the top 2.5%.
    assert bootstrap_mean_interval((0.0, 1.0, 1.0, 1.0), resamples=_RESAMPLES, seed=5) == (
        0.25,
        1.0,
    )


def test_the_band_holds_the_mean_it_is_a_band_of() -> None:
    # Not an identity - a percentile bootstrap can exclude the point estimate when the
    # distribution is skewed enough - but at these sizes it must not, and a band that has
    # drifted off its own estimate is the first sign the draw is not uniform over the indices.
    for values in ((0.0, 0.0, 0.0, 1.0), (0.2, 0.4, 0.6), (1.0, 1.0, 0.5, 0.0, 0.25)):
        mean = sum(values) / len(values)
        low, high = bootstrap_mean_interval(values, resamples=1000, seed=6)

        assert low <= mean <= high


def test_the_band_never_leaves_the_range_of_the_values() -> None:
    # Every resample mean is an average of values that were observed, so no endpoint can
    # exceed the largest or fall below the smallest. This is why the function needs no clamp
    # to [0, 1]: the caller's own numbers decide the range, and `stats` never learns that
    # these particular ones are rates.
    values = (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 1.0)

    for seed in range(4):
        low, high = bootstrap_mean_interval(values, resamples=500, seed=seed)

        assert min(values) <= low <= high <= max(values)


def test_the_same_seed_gives_the_same_band_twice() -> None:
    # The reproducibility SPEC 5.5 asks of every number in a report. The RNG is built inside
    # the call from the seed alone, so nothing a caller did earlier - including another
    # bootstrap - can move this band.
    values = (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 1.0)
    first = bootstrap_mean_interval(values, resamples=1000, seed=7)
    bootstrap_mean_interval(values, resamples=1000, seed=8)

    assert bootstrap_mean_interval(values, resamples=1000, seed=7) == first


def test_a_stronger_claim_buys_a_wider_band() -> None:
    # Level moves the two order statistics and nothing else: at L=0.5 the endpoints are the
    # 25th and 75th percentiles of the same 1000 resample means, at L=0.95 the 2.5th and
    # 97.5th. The same resamples in the same order, read further out, so the 95% band must
    # contain the 50% one strictly at both ends on a spread like this.
    values = (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 1.0)
    low, high = bootstrap_mean_interval(values, resamples=1000, seed=9, level=0.5)
    wide_low, wide_high = bootstrap_mean_interval(values, resamples=1000, seed=9, level=LEVEL_95)

    assert wide_low < low <= high < wide_high


def test_the_band_is_pinned_against_a_change_in_how_indices_are_drawn() -> None:
    # The one measured expectation in this file, and the only one that is not derived: this
    # band was computed on CPython 3.12 and written down. It exists to fail if the draw ever
    # stops being int(rng.random() * n) - swapping in rng.choice or rng.randrange keeps every
    # other test in this file green while changing every number a report prints, because those
    # methods are not documented as stable across CPython versions and random() is.
    #
    # If this test fails, the question is not what the new numbers are. It is whether the
    # change was meant, and if it was, ADR-0043 is what has to be superseded.
    values = (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 1.0)

    assert bootstrap_mean_interval(values, resamples=1000, seed=20260904) == (
        0.25,
        0.671875,
    )


def test_a_band_over_no_values_is_refused() -> None:
    # An empty sequence is a summary built from no tasks. There is nothing to resample, and
    # the caller's counting has already gone wrong somewhere upstream.
    with pytest.raises(ValueError, match="at least one value"):
        bootstrap_mean_interval((), resamples=1000, seed=1)


@pytest.mark.parametrize("resamples", [0, -1])
def test_a_band_from_no_resamples_is_refused(resamples: int) -> None:
    # Zero resamples has no order statistic to return, and returning the values' own mean as
    # a zero-width band would be a confident number nobody measured.
    with pytest.raises(ValueError, match="resamples"):
        bootstrap_mean_interval((0.0, 1.0), resamples=resamples, seed=1)


@pytest.mark.parametrize("level", [0.0, 1.0, -0.5, 1.5])
def test_a_band_at_an_impossible_level_is_refused(level: float) -> None:
    # A level of 1 asks for certainty from a finite resample and would silently return the
    # extremes; 0 and anything outside the unit interval is not a confidence level at all.
    with pytest.raises(ValueError, match="level"):
        bootstrap_mean_interval((0.0, 1.0), resamples=1000, seed=1, level=level)
