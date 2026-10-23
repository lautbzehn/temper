"""The statistics behind the numbers Temper reports: what a rate is worth, and when two differ.

A pass rate from a handful of trials is a rough measurement, and the honest
way to report it is with its interval. The intervals here are Wilson score
intervals, which behave at the edges where three of three and none of three
live, and the interval on a change is Newcombe's, built from the two. Every
trial of a case is taken as an independent draw of one chance, and a suite's
cases as the fixed set they are, so a suite's interval pools its trials and
errs, if at all, on the wide side.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Literal

CONFIDENCE = 0.95

# Past this many trials, a change too small to show isn't worth running for.
MOST_TRIALS = 10_000

Direction = Literal["better", "worse"]

# How many passed of how many were scored, as a pair.
Counts = tuple[float, int]


def wilson(passed: float, scored: int, *, among: int = 1) -> tuple[float, float]:
    """The interval a true rate is likely in, given `passed` of `scored` trials.

    `passed` may be fractional, so a rate can be asked about at a size it
    wasn't measured at. With nothing scored, anything is possible. `among`
    is how many such intervals are judged together: the interval widens so
    that one false alarm among them stays as unlikely as one alone.
    """
    if scored == 0:
        return (0.0, 1.0)
    z = _z(among)
    rate = passed / scored
    spread = z * z / scored
    center = (rate + spread / 2) / (1 + spread)
    half = z * math.sqrt(rate * (1 - rate) / scored + spread / (4 * scored)) / (1 + spread)
    # The bounds hold the rate by definition; a rounding hair must not put it outside.
    return (min(rate, max(0.0, center - half)), max(rate, min(1.0, center + half)))


def change_interval(before: Counts, after: Counts, *, among: int = 1) -> tuple[float, float]:
    """Where the true change from `before` to `after` is likely to be: Newcombe's interval."""
    (passed_before, scored_before), (passed_after, scored_after) = before, after
    if scored_before == 0 or scored_after == 0:
        return (-1.0, 1.0)
    rate_before, rate_after = passed_before / scored_before, passed_after / scored_after
    low_before, high_before = wilson(passed_before, scored_before, among=among)
    low_after, high_after = wilson(passed_after, scored_after, among=among)
    change = rate_after - rate_before
    # The change is at its lowest with the candidate at its lowest and the baseline at its highest.
    lower = change - math.hypot(rate_after - low_after, high_before - rate_before)
    upper = change + math.hypot(high_after - rate_after, rate_before - low_before)
    return (max(-1.0, lower), min(1.0, upper))


def direction_of(interval: tuple[float, float]) -> Direction | None:
    """Which way a change went when its interval leaves zero behind; None when it can't be told."""
    lower, upper = interval
    if lower > 0:
        return "better"
    if upper < 0:
        return "worse"
    return None


@dataclass(frozen=True, slots=True)
class Rate:
    """A pass rate as measured: how many passed of how many were scored."""

    passed: int
    scored: int

    @property
    def value(self) -> float | None:
        """The rate itself, or None when nothing was scored."""
        return self.passed / self.scored if self.scored else None

    @property
    def interval(self) -> tuple[float, float]:
        """Where the true rate is likely to be."""
        return wilson(self.passed, self.scored)

    @property
    def flaky(self) -> bool:
        """Whether the trials disagreed with each other: some passed, some didn't."""
        return 0 < self.passed < self.scored

    @property
    def noise_floor(self) -> float | None:
        """The smallest change from this rate that would be beyond noise at this size.

        Anything smaller is within noise. None when no change, however
        large, could be told from noise at this size.
        """
        return noise_floor(self.passed, self.scored)


@dataclass(frozen=True, slots=True)
class Difference:
    """How a rate changed from a baseline to a candidate, and how sure that change is.

    `among` is how many such changes are judged together, as a comparison
    judges one per case, so that one false alarm among them stays as
    unlikely as one alone.
    """

    baseline: Rate
    candidate: Rate
    among: int = 1

    @property
    def value(self) -> float | None:
        """The candidate's rate less the baseline's, or None when either scored nothing."""
        if self.baseline.value is None or self.candidate.value is None:
            return None
        return self.candidate.value - self.baseline.value

    @property
    def interval(self) -> tuple[float, float]:
        """Where the true change is likely to be."""
        before = (self.baseline.passed, self.baseline.scored)
        after = (self.candidate.passed, self.candidate.scored)
        return change_interval(before, after, among=self.among)

    @property
    def direction(self) -> Direction | None:
        """Which way the change went, when it went beyond noise; None when it can't be told."""
        return direction_of(self.interval)


def noise_floor(passed: float, scored: int) -> float | None:
    """The smallest change from `passed` of `scored`, either way, that would be beyond noise.

    Found by searching each direction for the least change whose interval
    leaves zero behind, so a change under the floor is never called beyond
    noise, whichever way it goes. None when no change at all could be.
    """
    if scored == 0:
        return None
    rate = passed / scored
    floors = (_least_change(rate, scored, room) for room in (1 - rate, -rate) if room)
    return min((floor for floor in floors if floor is not None), default=None)


def _least_change(rate: float, scored: int, room: float) -> float | None:
    """The least change toward `room`, as far as the rate can move that way, that shows."""

    def clears(change: float) -> bool:
        moved = ((rate + change) * scored, scored)
        interval = change_interval((rate * scored, scored), moved)
        return direction_of(interval) is not None

    if not clears(room):
        return None
    low, high = 0.0, room
    for _ in range(40):
        middle = (low + high) / 2
        low, high = (low, middle) if clears(middle) else (middle, high)
    return abs(high)


def trials_to_tell(before: float, after: float) -> int | None:
    """How many scored trials of each it takes for a change from `before` to `after` to show.

    None when the rates are the same, or no sensible number of trials would do.
    """
    if before == after:
        return None
    for scored in range(1, MOST_TRIALS + 1):
        if direction_of(change_interval((before * scored, scored), (after * scored, scored))):
            return scored
    return None


def _z(among: int) -> float:
    """The normal quantile for the confidence, shared across `among` judgments made together."""
    return NormalDist().inv_cdf(1 - (1 - CONFIDENCE) / (2 * among))
