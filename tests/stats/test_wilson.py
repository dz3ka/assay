"""The one arithmetic in Assay that nobody may check against itself.

Every expected band below is worked out by hand from the closed form and written as a literal
(CLAUDE.md): a test that recomputed the interval the way :func:`wilson_interval` does would
agree with any arithmetic, including the wrong one. Each case carries its derivation in a
comment - the centre, the half-width, and the two intermediate products - so a reader with a
calculator can settle the number without reading the implementation.

The formula, for ``k`` successes in ``n`` trials at ``z`` standard normal deviates:

    centre = (k + z^2/2) / (n + z^2)
    half   = z / (n + z^2) * sqrt(k(n - k)/n + z^2/4)

with ``z = 1.959963984540054`` for 95%, so ``z^2 = 3.8414588206941250``.

One test here is the anti-self-test the rest exists for: ``0/5`` must *not* be ``[0, 0]``,
which is exactly what the normal approximation returns and what CLAUDE.md's measurement rules
forbid the harness from ever printing.
"""

import pytest

from assay.stats import Z_95, wilson_interval

# The hand-computed values below are quoted to ten decimal places. Double precision carries
# about sixteen significant digits, so rounding to ten is exact agreement rather than a
# tolerance: a band that differs from the literal in the eleventh place still passes, and one
# that differs in the tenth is a different interval.
_PLACES = 10


def _at(interval: tuple[float, float]) -> tuple[float, float]:
    """The interval at the width the literals are written to."""
    low, high = interval
    return round(low, _PLACES), round(high, _PLACES)


def test_no_successes_in_five_trials() -> None:
    # n=5, k=0: n + z^2 = 8.8414588207. centre = (0 + 1.9207294103)/8.8414588207 = 0.2172412324.
    # half = (1.959963984540054/8.8414588207) * sqrt(0 + 0.9603647052)
    #      = 0.2216788003 * 0.9799819923 = 0.2172412324.
    # centre - half = 0 exactly; centre + half = 0.4344824648.
    assert _at(wilson_interval(0, 5)) == (0.0, 0.4344824648)


def test_five_successes_in_five_trials() -> None:
    # n=5, k=5: centre = (5 + 1.9207294103)/8.8414588207 = 0.7827587676, and the half-width is
    # the one above - k(n-k) is 0 at both ends - so low = 0.5655175352 and high = 1 exactly.
    assert _at(wilson_interval(5, 5)) == (0.5655175352, 1.0)


def test_one_success_in_two_trials() -> None:
    # n=2, k=1: n + z^2 = 5.8414588207. centre = (1 + 1.9207294103)/5.8414588207 = 0.5 exactly,
    # the point estimate, because k = n/2. half = (1.959963984540054/5.8414588207) *
    # sqrt(1*1/2 + 0.9603647052) = 0.3355264575 * 1.2084555040 = 0.4054687943.
    assert _at(wilson_interval(1, 2)) == (0.0945312057, 0.9054687943)


def test_one_success_in_five_trials() -> None:
    # n=5, k=1: centre = (1 + 1.9207294103)/8.8414588207 = 0.3303447394 - above the point
    # estimate 0.2, which is the shrinkage towards 1/2 that makes this interval usable at
    # small n. half = 0.2216788003 * sqrt(1*4/5 + 0.9603647052)
    #              = 0.2216788003 * 1.3267873625 = 0.2941206308.
    assert _at(wilson_interval(1, 5)) == (0.0362241086, 0.6244653702)


def test_thirty_successes_in_a_hundred_trials() -> None:
    # The large-n case, where the band is narrow and the centre has nearly stopped moving:
    # n + z^2 = 103.8414588207, centre = (30 + 1.9207294103)/103.8414588207 = 0.3073986996
    # against a point estimate of 0.3. half = (1.959963984540054/103.8414588207) *
    # sqrt(30*70/100 + 0.9603647052) = 0.0188745806 * 4.6861887185 = 0.0884498467.
    assert _at(wilson_interval(30, 100)) == (0.2189488529, 0.3958485463)


def test_no_successes_does_not_report_certainty() -> None:
    # The anti-self-test, and the reason the normal approximation is banned (CLAUDE.md): at
    # k=0 it returns p +/- z*sqrt(p(1-p)/n) = 0 +/- 0, an interval of zero width claiming a
    # tool fails every task it will ever be given. Wilson's upper end stays where the evidence
    # actually is - five failures leave rates up to 0.43 entirely plausible.
    low, high = wilson_interval(0, 5)

    assert (low, high) != (0.0, 0.0)
    assert high > 0.43


def test_the_band_is_symmetric_under_swapping_successes_for_failures() -> None:
    # k successes out of n and n-k out of n are the same measurement read from the other end,
    # so their intervals must be mirror images about 1/2.
    for successes in range(6):
        low, high = wilson_interval(successes, 5)
        mirror_low, mirror_high = wilson_interval(5 - successes, 5)

        assert round(low, _PLACES) == round(1.0 - mirror_high, _PLACES)
        assert round(high, _PLACES) == round(1.0 - mirror_low, _PLACES)


def test_the_band_narrows_as_the_sample_grows() -> None:
    # One half of the point estimate held fixed at 1/2 while n grows: more trials must buy
    # more certainty, monotonically, or the interval is not reading the sample.
    widths = [high - low for low, high in (wilson_interval(n, 2 * n) for n in (1, 2, 5, 50))]

    assert widths == sorted(widths, reverse=True)
    assert widths[-1] < 0.2


def test_every_band_stays_inside_the_unit_interval() -> None:
    # A proportion outside [0, 1] is not a wider claim, it is an unrenderable one: the report's
    # Interval refuses it, so the clamp belongs here rather than in the caller.
    for trials in range(1, 12):
        for successes in range(trials + 1):
            low, high = wilson_interval(successes, trials)

            assert 0.0 <= low <= high <= 1.0


def test_a_narrower_confidence_level_gives_a_narrower_band() -> None:
    # z is an argument rather than a constant so that M4 can report a level other than 95%
    # without a second function. One standard deviate is about 68%, and a weaker claim covers
    # less ground: same data, narrower band, centred on the same value.
    low, high = wilson_interval(1, 2, z=1.0)
    wide_low, wide_high = wilson_interval(1, 2, z=Z_95)

    assert wide_low < low < high < wide_high


@pytest.mark.parametrize("trials", [0, -1])
def test_a_band_over_no_trials_is_refused(trials: int) -> None:
    # Zero trials is a division by zero dressed as a measurement. The caller has a bug - a
    # summary built from no results at all - and raising names it where it happened.
    with pytest.raises(ValueError, match="trials"):
        wilson_interval(0, trials)


@pytest.mark.parametrize(("successes", "trials"), [(3, 2), (-1, 5)])
def test_a_band_over_an_impossible_count_is_refused(successes: int, trials: int) -> None:
    # More successes than trials, or a negative count, is upstream arithmetic that has already
    # gone wrong. Clamping it would publish a band derived from a number nobody measured.
    with pytest.raises(ValueError, match="successes"):
        wilson_interval(successes, trials)
