"""Two runs of the same cases set side by side: what changed, where, and whether to ship.

A change is only worth something against the noise two runs of one thing
would show, so every change comes with its interval. The verdict holds a
candidate for a change that is worse beyond that noise, overall or on any
one case, and refuses to call anything when a case has nothing scored. A
case that broke is a regression even when the average hides it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from temper.errors import RunError
from temper.stats import Difference, trials_to_tell

if TYPE_CHECKING:
    from temper.results import Manifest, Run

Finding = Literal["better", "worse", "undecided", "unmeasured"]


@dataclass(frozen=True, slots=True)
class Change:
    """One case in both runs: how its rate differs between them."""

    case_id: str
    difference: Difference


@dataclass(frozen=True, slots=True)
class Comparison:
    """A candidate run against a baseline: every case's change, the overall one, and the call.

    Each case's change is judged among all the cases, so one false alarm
    across the suite stays as unlikely as one alone; the overall change
    stands on its own.
    """

    baseline: Manifest
    candidate: Manifest
    changes: tuple[Change, ...]
    overall: Difference

    @property
    def regressed(self) -> tuple[Change, ...]:
        """The cases that got worse beyond noise."""
        return tuple(change for change in self.changes if change.difference.direction == "worse")

    @property
    def improved(self) -> tuple[Change, ...]:
        """The cases that got better beyond noise."""
        return tuple(change for change in self.changes if change.difference.direction == "better")

    @property
    def unmeasured(self) -> tuple[Change, ...]:
        """The cases with nothing scored in one run or both, where no change can be told at all."""
        return tuple(change for change in self.changes if change.difference.value is None)

    @property
    def finding(self) -> Finding:
        """What the comparison found, worst first: unmeasured, worse, better, or undecided."""
        if self.unmeasured:
            return "unmeasured"
        if self.regressed or self.overall.direction == "worse":
            return "worse"
        if self.overall.direction == "better":
            return "better"
        return "undecided"

    @property
    def ship(self) -> bool:
        """Whether the candidate may ship: every case measured, and nothing worse beyond noise."""
        return self.finding in {"better", "undecided"}

    @property
    def judges_differ(self) -> bool:
        """Whether the runs were judged by different models, which a change may really be."""
        return self.baseline.judge != self.candidate.judge

    @property
    def trials_to_tell(self) -> int | None:
        """Trials per case that would lift the overall change out of the noise, if any would."""
        before, after = self.overall.baseline.value, self.overall.candidate.value
        if before is None or after is None:
            return None
        scored = trials_to_tell(before, after)
        return None if scored is None else math.ceil(scored / len(self.changes))


def compare(baseline: Run, candidate: Run) -> Comparison:
    """Set a candidate run against a baseline, case by case and overall.

    Raises:
        RunError: the runs aren't of the same cases, or one predates comparing.
    """
    for run in (baseline, candidate):
        if run.manifest.cases_fingerprint is None:
            raise RunError(
                f"run {run.manifest.run_id} was kept before runs could be compared; run it again"
            )
    if baseline.manifest.cases_fingerprint != candidate.manifest.cases_fingerprint:
        raise RunError(
            f"runs {baseline.manifest.run_id} and {candidate.manifest.run_id} are of different "
            "cases; compare two runs of the same suite's cases"
        )
    before, after = baseline.rates, candidate.rates
    case_ids = baseline.manifest.case_ids
    changes = tuple(
        Change(case_id, Difference(before[case_id], after[case_id], among=len(case_ids)))
        for case_id in case_ids
    )
    return Comparison(
        baseline.manifest, candidate.manifest, changes, Difference(baseline.rate, candidate.rate)
    )
