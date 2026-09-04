"""The third arithmetic in Assay that nobody may check against itself.

There is no scipy here to compare against and there is deliberately not going to be one, so
every expected p below is worked out by hand from the binomial distribution and written as a
literal (CLAUDE.md: hand-computed known values, never the function itself). A test that summed
the same binomial coefficients the implementation sums would agree with any arithmetic,
including an off-by-one in the tail.

The estimator, for ``b`` tasks only tool A solved and ``c`` tasks only tool B solved:

    n = b + c discordant tasks, m = min(b, c), and under the null hypothesis that the tools are
    the same the number falling to either side is Binomial(n, 1/2), so

        p = min(1, 2 * sum(C(n, i) for i in 0..m) / 2^n)

Two things make that hand-computable. The coefficients are small integers at the counts this
harness produces, and the result is always a dyadic rational - some integer over a power of two
- which is exact in binary floating point. So the literals below are compared with ``==`` rather
than to a tolerance, and each one carries its own numerator and denominator in a comment. That
is a property of this distribution, not of the function.

The clamp deserves its own note, because it looks like a fudge and is not. Doubling the smaller
tail is the sum over ``{X <= m}`` and ``{X >= n - m}`` - every outcome at least as lopsided as
the observed one - and those two sets are disjoint unless ``m >= n - m``, which happens exactly
when ``b == c``. At an even split every possible outcome is at least as lopsided as the one
observed, so the honest p is 1 and ``min`` is what says so. Two cases below pin that.
"""

import pytest

from assay.stats import mcnemar_exact_p


def test_no_discordant_tasks_is_no_evidence() -> None:
    # b = c = 0: the tools solved exactly the same tasks, so there is no split to read. n = 0,
    # m = 0, the sum is C(0,0) = 1 over 2^0 = 1, and 2 * 1 clamps to 1.0 - the largest p there
    # is, which is the only honest answer when the comparison saw nothing to compare.
    assert mcnemar_exact_p(0, 0) == 1.0


def test_three_tasks_won_by_one_tool_alone() -> None:
    # b = 3, c = 0: n = 3, m = 0, so the sum is C(3,0) = 1 and p = 2 * 1 / 8 = 0.25. Three
    # coin flips all landing the same way is the smallest evidence anybody argues about, and
    # this is why it is not enough: one suite in four would do it by chance.
    assert mcnemar_exact_p(3, 0) == 0.25


def test_six_tasks_against_one() -> None:
    # b = 6, c = 1: n = 7, m = 1, sum = C(7,0) + C(7,1) = 1 + 7 = 8, and p = 2 * 8 / 128
    # = 16/128 = 0.125. The single task the other tool solved costs a factor of eight.
    assert mcnemar_exact_p(6, 1) == 0.125


def test_eight_tasks_against_one() -> None:
    # b = 8, c = 1: n = 9, m = 1, sum = C(9,0) + C(9,1) = 1 + 9 = 10, so p = 20 / 512
    # = 0.0390625. The first split in this file a reader would call significant - and the
    # report still refuses to name a winner on it (ADR-0005, ADR-0044).
    assert mcnemar_exact_p(8, 1) == 0.0390625


def test_ten_tasks_against_two() -> None:
    # b = 10, c = 2: n = 12, m = 2, sum = C(12,0) + C(12,1) + C(12,2) = 1 + 12 + 66 = 79, and
    # p = 158 / 4096 = 79/2048 = 0.03857421875, exact in binary. Twelve discordant tasks is
    # about the largest count the suites mined so far produce, which is the regime the exact
    # test was chosen for.
    assert mcnemar_exact_p(10, 2) == 0.03857421875


def test_an_even_split_is_the_case_the_clamp_exists_for() -> None:
    # b = c = 2: n = 4, m = 2, sum = C(4,0) + C(4,1) + C(4,2) = 1 + 4 + 6 = 11, so twice the
    # tail is 22/16 = 1.375 - not a probability. The two tails overlap because m = n - m = 2,
    # and their union is every outcome there is, so the honest p is exactly 1.
    assert mcnemar_exact_p(2, 2) == 1.0


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_a_dead_heat_never_reads_as_evidence(count: int) -> None:
    # The general form of the case above: whenever the two tools took the same number of tasks
    # off each other, every possible split is at least as lopsided as the one observed. A p
    # below 1 here would mean the test had found evidence in a tie.
    assert mcnemar_exact_p(count, count) == 1.0


def test_the_p_does_not_depend_on_which_tool_is_named_first() -> None:
    # McNemar asks whether the tools differ, not which is ahead, so the two arguments are
    # interchangeable. An asymmetry here would mean the report's column order had become an
    # input to its statistics.
    for only_a in range(7):
        for only_b in range(7):
            assert mcnemar_exact_p(only_a, only_b) == mcnemar_exact_p(only_b, only_a)


def test_a_more_lopsided_split_of_the_same_tasks_is_stronger_evidence() -> None:
    # Ten discordant tasks, split six ways. Hand-computed from the same sum, m rising by one
    # each step: 2*1/1024 = 0.001953125, 2*11/1024 = 0.021484375, 2*56/1024 = 0.109375,
    # 2*176/1024 = 0.34375, 2*386/1024 = 0.75390625, and 2*638/1024 = 1.24609375 -> 1.0.
    splits = [mcnemar_exact_p(10 - only_b, only_b) for only_b in range(6)]

    assert splits == [0.001953125, 0.021484375, 0.109375, 0.34375, 0.75390625, 1.0]
    assert splits == sorted(splits)


def test_each_further_one_sided_task_halves_the_p() -> None:
    # With c = 0 the sum is always C(n,0) = 1, so p = 2 / 2^n exactly and every extra task
    # that only one tool solves is one more coin landing the same way. Written out because it
    # is the clearest reading of what the number means.
    one_sided = [mcnemar_exact_p(only_a, 0) for only_a in (3, 4, 5, 6)]

    assert one_sided == [0.25, 0.125, 0.0625, 0.03125]


def test_every_p_is_a_probability() -> None:
    # The clamp is the only place this could go wrong, and it goes wrong quietly: a p above 1
    # renders as a number and is not one. Zero is excluded because the observed split is always
    # one of the outcomes being summed, so no finite count can drive the tail to nothing.
    for only_a in range(12):
        for only_b in range(12):
            assert 0.0 < mcnemar_exact_p(only_a, only_b) <= 1.0


@pytest.mark.parametrize(("only_a", "only_b"), [(-1, 0), (0, -1), (-2, -3), (-1, 4)])
def test_a_negative_count_is_refused(only_a: int, only_b: int) -> None:
    # A negative count of tasks is upstream arithmetic that has already gone wrong - a pairing
    # that subtracted the wrong sets. math.comb would raise on its own for some of these and
    # return a number for others, so the check is here, where it can name both arguments.
    with pytest.raises(ValueError, match="negative"):
        mcnemar_exact_p(only_a, only_b)
