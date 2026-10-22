"""How often the judge agrees with a person: the number a judge is trusted on, or isn't.

Agreement alone flatters a judge when most answers pass, since two raters who
always say yes agree every time. Cohen's kappa takes that chance agreement
out, so trust takes both, and enough labels to mean something.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from temper.checks import judge_checks

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from temper.labels import Label
    from temper.results import Run
    from temper.suite import Suite

# What trusting a judge takes: this many labels, this much agreement, and this much kappa.
FLOOR = 20
TRUSTED = 0.9
KAPPA = 0.6


@dataclass(frozen=True, slots=True)
class Disagreement:
    """One answer the judge and the person called differently."""

    case_id: str
    trial: int
    property: str
    judge_passed: bool
    judge_reason: str
    label_passed: bool


@dataclass(frozen=True, slots=True)
class Calibration:
    """The judge against the labels: a two-by-two count, agreement by property, and every split."""

    both_passed: int
    judge_only: int
    person_only: int
    both_failed: int
    without_verdict: int
    unmatched: int
    reworded: int
    by_property: Mapping[str, tuple[int, int]]
    disagreements: tuple[Disagreement, ...]

    @property
    def labeled(self) -> int:
        """How many labels met a verdict."""
        return self.both_passed + self.judge_only + self.person_only + self.both_failed

    @property
    def agreed(self) -> int:
        """How many of those the judge called the same way."""
        return self.both_passed + self.both_failed

    @property
    def agreement(self) -> float | None:
        """The share of labels the judge agreed with, or None when no label met a verdict."""
        return self.agreed / self.labeled if self.labeled else None

    @property
    def kappa(self) -> float | None:
        """Cohen's kappa: agreement beyond what raters who pass this often would reach by chance.

        None when there's nothing to compare, or when both always said the
        same thing, which leaves chance nothing to be beyond.
        """
        if self.agreement is None:
            return None
        judge_pass = (self.both_passed + self.judge_only) / self.labeled
        person_pass = (self.both_passed + self.person_only) / self.labeled
        by_chance = judge_pass * person_pass + (1 - judge_pass) * (1 - person_pass)
        return None if by_chance == 1 else (self.agreement - by_chance) / (1 - by_chance)

    @property
    def trusted(self) -> bool | None:
        """Whether the judge earned trust: enough labels, agreement at the bar, kappa past chance.

        None with fewer labels than the floor, since a handful can't tell a
        judge from a coin.
        """
        if self.labeled < FLOOR:
            return None
        agreement, kappa = self.agreement, self.kappa
        return (
            agreement is not None and agreement >= TRUSTED and kappa is not None and kappa >= KAPPA
        )


def calibrate(suite: Suite, run: Run, labels: Iterable[Label]) -> Calibration:
    """Compare the judge's verdict with the person's label on every labeled answer in the run.

    A label names its answer by fingerprint and its property by wording, so a
    label about an answer this run doesn't have is left out and counted, and
    one whose property has been reworded since still finds its check by
    position, and is counted as reworded.
    """
    results = {(result.case_id, result.trial): result for result in run.results}
    properties = {
        (case.id, index): check.property
        for case in suite.cases
        for index, check in judge_checks(case)
    }
    positions = {(case_id, wording): index for (case_id, index), wording in properties.items()}
    by_property = {wording: [0, 0] for wording in properties.values()}
    tally: Counter[tuple[bool, bool]] = Counter()
    without_verdict = unmatched = reworded = 0
    disagreements: list[Disagreement] = []
    for label in labels:
        result = results.get((label.case_id, label.trial))
        if result is None or result.answer.fingerprint != label.answer:
            unmatched += 1
            continue
        index = positions.get((label.case_id, label.property))
        if index is None:
            if (label.case_id, label.check) not in properties:
                unmatched += 1
                continue
            index = label.check
            reworded += 1
        wording = properties[label.case_id, index]
        grade = result.grades[index]
        if grade.passed is None:
            without_verdict += 1
            continue
        tally[grade.passed, label.passed] += 1
        counts = by_property[wording]
        counts[1] += 1
        counts[0] += grade.passed == label.passed
        if grade.passed != label.passed:
            disagreements.append(
                Disagreement(
                    label.case_id, label.trial, wording, grade.passed, grade.reason, label.passed
                )
            )
    return Calibration(
        both_passed=tally[True, True],
        judge_only=tally[True, False],
        person_only=tally[False, True],
        both_failed=tally[False, False],
        without_verdict=without_verdict,
        unmatched=unmatched,
        reworded=reworded,
        by_property={name: (agreed, labeled) for name, (agreed, labeled) in by_property.items()},
        disagreements=tuple(disagreements),
    )
