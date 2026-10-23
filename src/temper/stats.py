"""The statistics behind the numbers Temper reports: what a rate is worth, and when two differ.

A pass rate from a handful of trials is a rough measurement, and the honest
way to report it is with its interval. The intervals here are Wilson score
intervals, which behave at the edges where three of three and none of three
live, and the interval on a difference is Newcombe's, built from the two.
Every trial of a case is taken as an independent draw of one chance, and a
suite's cases as the fixed set they are, so a suite's interval pools its
trials and errs, if at all, on the wide side.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Literal

CONFIDENCE = 0.95
_Z = NormalDist().inv_cdf((1 + CONFIDENCE) / 2)

# Past this many trials, a difference too small to show isn't worth running for.
MOST_TRIALS = 10_000

Direction = Literal["better", "worse"]


def wilson(passed: float, scored: int) -> tuple[float, float]:
    """The interval a true rate is likely in, given `passed` of `scored` trials.

    `passed` may be fractional, so a rate can be asked about at a size it
    wasn't measured at. With nothing scored, anything is possible.
    """
    if scored == 0:
        return (0.0, 1.0)
    rate = passed / scored
    spread = _Z * _Z / scored
    center = (rate + spread / 2) / (1 + spread)
    half = _Z * math.sqrt(rate * (1 - rate) / scored + spread / (4 * scored)) / (1 + spread)
    # The bounds hold the rate by definition; a rounding hair must not put it outside.
    return (min(rate, max(0.0, center - half)), max(rate, min(1.0, center + half)))


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
    def noise_floor(self) -> float:
        """How far apart two runs of this very thing could land by chance.

        The half-width of the interval on the difference between this rate
        and itself: a change smaller than this is within noise at this size.
        """
        return noise_floor(self.passed, self.scored)


def noise_floor(passed: float, scored: int) -> float:
    """The half-width of the difference interval between `passed` of `scored` and its twin."""
    if scored == 0:
        return 1.0
    rate = passed / scored
    lower, upper = wilson(passed, scored)
    return math.sqrt((rate - lower) ** 2 + (upper - rate) ** 2)


@dataclass(frozen=True, slots=True)
class Difference:
    """How a rate changed from a baseline to a candidate, and how sure that change is."""

    baseline: Rate
    candidate: Rate

    @property
    def value(self) -> float | None:
        """The candidate's rate less the baseline's, or None when either scored nothing."""
        if self.baseline.value is None or self.candidate.value is None:
            return None
        return self.candidate.value - self.baseline.value

    @property
    def interval(self) -> tuple[float, float]:
        """Where the true change is likely to be: Newcombe's interval from the two rates'."""
        before, after = self.baseline.value, self.candidate.value
        if before is None or after is None:
            return (-1.0, 1.0)
        low_before, high_before = self.baseline.interval
        low_after, high_after = self.candidate.interval
        # The change is low when the candidate is at its lowest and the baseline at its highest.
        lower = after - before - math.hypot(after - low_after, high_before - before)
        upper = after - before + math.hypot(high_after - after, before - low_before)
        return (max(-1.0, lower), min(1.0, upper))

    @property
    def direction(self) -> Direction | None:
        """Which way the change went, when it went beyond noise; None when it can't be told."""
        lower, upper = self.interval
        if lower > 0:
            return "better"
        if upper < 0:
            return "worse"
        return None


def trials_to_tell(rate: float, change: float) -> int | None:
    """How many scored trials it takes for a change of `change` to clear the noise floor at `rate`.

    None when no sensible number of trials would do, as for a change of nothing.
    """
    wanted = abs(change)
    if wanted == 0:
        return None
    for scored in range(1, MOST_TRIALS + 1):
        if noise_floor(rate * scored, scored) < wanted:
            return scored
    return None
