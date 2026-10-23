from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from temper.stats import Difference, Rate, noise_floor, trials_to_tell, wilson

counts = st.integers(min_value=0, max_value=200)


@st.composite
def rates(draw: st.DrawFn, *, at_least: int = 0) -> Rate:
    scored = draw(st.integers(min_value=at_least, max_value=200))
    return Rate(passed=draw(st.integers(min_value=0, max_value=scored)), scored=scored)


@pytest.mark.parametrize(
    ("passed", "scored", "lower", "upper"),
    [
        (3, 3, 0.44, 1.0),
        (0, 3, 0.0, 0.56),
        (12, 15, 0.55, 0.93),
        (80, 100, 0.71, 0.87),
    ],
)
def test_wilson_matches_the_textbook(passed: int, scored: int, lower: float, upper: float) -> None:
    assert wilson(passed, scored) == pytest.approx((lower, upper), abs=0.005)


def test_newcombes_interval_matches_his_own_worked_example() -> None:
    # Newcombe (1998), Statistics in Medicine 17:873, example (a), method 10.
    change = Difference(baseline=Rate(48, 80), candidate=Rate(56, 70))

    assert change.value == pytest.approx(0.2)
    assert change.interval == pytest.approx((0.0524, 0.3339), abs=0.0001)


def test_three_of_three_is_a_rough_measurement() -> None:
    rate = Rate(3, 3)

    assert rate.value == 1.0
    assert rate.interval[0] < 0.5
    assert rate.noise_floor == pytest.approx(0.56, abs=0.005)
    assert not rate.flaky


def test_nothing_scored_means_anything_is_possible() -> None:
    nothing = Rate(0, 0)

    assert nothing.value is None
    assert nothing.interval == (0.0, 1.0)
    assert nothing.noise_floor == 1.0
    assert Difference(nothing, Rate(3, 3)).value is None
    assert Difference(nothing, Rate(3, 3)).interval == (-1.0, 1.0)
    assert Difference(nothing, Rate(3, 3)).direction is None


def test_a_case_that_broke_shows_beyond_noise_even_at_three_trials() -> None:
    broke = Difference(Rate(3, 3), Rate(0, 3))

    assert broke.value == -1.0
    assert broke.direction == "worse"
    assert broke.interval[1] < 0


def test_a_case_that_wobbled_does_not() -> None:
    wobbled = Difference(Rate(3, 3), Rate(2, 3))

    assert wobbled.value == pytest.approx(-1 / 3)
    assert wobbled.direction is None


def test_trials_to_tell_grows_as_the_change_shrinks() -> None:
    big, small, tiny = (trials_to_tell(0.8, change) for change in (0.5, 0.1, 0.02))

    assert big is not None
    assert small is not None
    assert tiny is not None
    assert big < small < tiny
    assert trials_to_tell(0.8, 0.0) is None
    assert trials_to_tell(0.5, 0.0001) is None


@given(rates())
def test_an_interval_holds_its_rate_and_stays_in_bounds(rate: Rate) -> None:
    lower, upper = rate.interval

    assert 0.0 <= lower <= upper <= 1.0
    if rate.value is not None:
        assert lower <= rate.value <= upper


@given(rates())
def test_an_interval_is_the_same_seen_from_either_side(rate: Rate) -> None:
    mirrored = Rate(rate.scored - rate.passed, rate.scored)

    lower, upper = rate.interval
    assert mirrored.interval == pytest.approx((1 - upper, 1 - lower))
    assert mirrored.noise_floor == pytest.approx(rate.noise_floor)


@given(st.floats(min_value=0, max_value=1), st.integers(min_value=1, max_value=500))
def test_more_trials_never_widen_an_interval_or_raise_the_floor(rate: float, scored: int) -> None:
    lower, upper = wilson(rate * scored, scored)
    lower_more, upper_more = wilson(rate * (scored + 1), scored + 1)

    assert upper_more - lower_more <= upper - lower + 1e-12
    assert (
        noise_floor(rate * (scored + 1), scored + 1) <= noise_floor(rate * scored, scored) + 1e-12
    )


@given(rates(), rates())
def test_a_difference_holds_its_value_and_is_the_rates_difference_reversed(
    baseline: Rate, candidate: Rate
) -> None:
    forward = Difference(baseline, candidate)
    backward = Difference(candidate, baseline)

    lower, upper = forward.interval
    assert -1.0 <= lower <= upper <= 1.0
    if forward.value is not None:
        assert lower <= forward.value <= upper
        assert backward.value == pytest.approx(-forward.value)
    assert backward.interval == pytest.approx((-upper, -lower))


@given(rates(at_least=1), rates(at_least=1))
def test_a_measured_change_is_never_known_exactly(baseline: Rate, candidate: Rate) -> None:
    lower, upper = Difference(baseline, candidate).interval

    assert lower < upper


@given(rates(at_least=1))
def test_a_rate_against_itself_is_within_noise_by_exactly_the_floor(rate: Rate) -> None:
    same = Difference(rate, rate)

    assert same.value == 0
    assert same.direction is None
    assert same.interval == pytest.approx((-rate.noise_floor, rate.noise_floor))


@given(rates(at_least=1), rates(at_least=1))
def test_beyond_noise_means_the_interval_leaves_zero_behind(
    baseline: Rate, candidate: Rate
) -> None:
    change = Difference(baseline, candidate)
    lower, upper = change.interval

    assert (change.direction == "better") == (lower > 0)
    assert (change.direction == "worse") == (upper < 0)
    if change.direction is not None:
        assert change.value is not None
        assert math.copysign(1, change.value) == (1 if change.direction == "better" else -1)
