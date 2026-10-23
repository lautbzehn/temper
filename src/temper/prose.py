"""The sentences Temper says about a run or a comparison, wherever they are shown.

The terminal and the scorecard both read from here, so the two can never
tell a reader different things about the same run.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from temper.wording import change_span, dollars, gap, percent, plural, points, span

if TYPE_CHECKING:
    from collections.abc import Sequence

    from temper.comparison import Change, Comparison
    from temper.results import Manifest, Run, TrialFailure, TrialResult
    from temper.stats import Difference, Rate


def described(manifest: Manifest) -> str:
    """`claude claude-sonnet-5-5 · judge claude-opus-5-5 · 5 cases × 3 trials`."""
    model = f" {manifest.model}" if manifest.model else ""
    judged = f" · judge {manifest.judge}" if manifest.judge else ""
    cases = plural(len(manifest.case_ids), "case")
    return f"{manifest.provider}{model}{judged} · {cases} × {plural(manifest.trials, 'trial')}"


def count(rate: Rate) -> str:
    """`3/3`: how many passed of how many were scored."""
    return f"{rate.passed}/{rate.scored}"


def tally(run: Run) -> str:
    """`14 of 15 scored trials passed (93%, likely 70 to 99%)`."""
    rate = run.rate
    likely = (
        f" ({percent(rate.value)}, likely {span(rate.interval)})" if rate.value is not None else ""
    )
    return f"{rate.passed} of {plural(rate.scored, 'scored trial')} passed{likely}"


def left_out(run: Run) -> list[str]:
    """What the tally leaves out, and why: answers cut off, refused, unjudged, or never given."""
    counts = [
        (run.count("truncated"), "truncated"),
        (run.count("refused"), "refused"),
        (run.without_verdict, "with no verdict"),
    ]
    said = [f"{count} {what}" for count, what in counts if count]
    if run.failures:
        said.append(f"{plural(len(run.failures), 'attempt')} failed, not scored")
    return said


def noise(rate: Rate) -> str:
    """How big a difference has to be, at this size, before it means anything."""
    floor = rate.noise_floor
    if floor is None:
        return "No difference, however large, could be told from noise at this size."
    return f"Differences under {gap(floor)} are within noise at this size."


def noise_for(compared: Comparison) -> str:
    """The noise line a comparison is read against: the baseline's, at its size."""
    return noise(compared.overall.baseline)


def caveats(compared: Comparison) -> list[str]:
    """What a reader must weigh before the numbers: for now, two runs judged by different models."""
    if not compared.judges_differ:
        return []
    named = [manifest.judge or "no judge" for manifest in (compared.baseline, compared.candidate)]
    return [
        (
            f"The runs were judged by different models, {named[0]} and {named[1]}, so a change "
            "may be the judge's and not the target's."
        )
    ]


def flaky(run: Run) -> str | None:
    """`1 flaky case: passed some trials, failed others.`, when there are any."""
    if not run.flaky:
        return None
    return f"{plural(len(run.flaky), 'flaky case')}: passed some trials, failed others."


def cost(run: Run) -> str | None:
    """What the run cost at list price, the judge's share, and what was really spent if less."""
    total = run.cost_usd
    if total is None:
        return None
    judge = f", {dollars(run.verdicts_usd)} of it on the judge" if run.verdicts_usd else ""
    spent = (run.manifest.spent_usd or 0.0) if run.manifest.charges else 0.0
    if dollars(spent) == dollars(total):
        return f"{dollars(total)} spent{judge}"
    paid = f"{dollars(spent)} spent" if spent else "nothing spent"
    return f"{dollars(total)} at list price{judge} · {paid}"


def failures_by_case(failures: Sequence[TrialFailure]) -> dict[str, list[TrialFailure]]:
    """Each case's failed attempts."""
    grouped: dict[str, list[TrialFailure]] = {}
    for failure in failures:
        grouped.setdefault(failure.case_id, []).append(failure)
    return grouped


def notes(rate: Rate, results: Sequence[TrialResult], failures: Sequence[TrialFailure]) -> str:
    """What a reader should know about a case beyond its pass count, briefly."""
    said: list[str] = ["flaky"] if rate.flaky else []
    first_miss = next(
        (
            f"trial {result.trial}: {textwrap.shorten(grade.reason, 72, placeholder='…')}"
            for result in results
            if result.status == "complete"
            for grade in result.grades
            if not grade.passed
        ),
        None,
    )
    if first_miss:
        said.append(first_miss)
    said.extend(
        f"{number} {status}"
        for status in ("truncated", "refused")
        if (number := sum(result.status == status for result in results))
    )
    if failures:
        kinds = ", ".join(sorted({failure.kind for failure in failures}))
        said.append(f"{plural(len(failures), 'attempt')} failed: {kinds}")
    return " · ".join(said)


def changed(difference: Difference) -> str:
    """`-100 points, worse beyond noise`, or `+0 points`."""
    if difference.value is None:
        return "nothing scored"
    beyond = f", {difference.direction} beyond noise" if difference.direction else ""
    return f"{points(difference.value)}{beyond}"


def overall(compared: Comparison) -> str | None:
    """`Overall 87% → 67%, -20 points (likely -45 to +8 points).`, or None with nothing scored."""
    change = compared.overall
    before, after, value = change.baseline.value, change.candidate.value, change.value
    if before is None or after is None or value is None:
        return None
    return (
        f"Overall {percent(before)} → {percent(after)}, {points(value)} "
        f"(likely {change_span(change.interval)})."
    )


def verdict(compared: Comparison) -> str:
    """The call in a sentence: none with a case unmeasured, hold for anything worse, else ship."""
    if compared.finding == "unmeasured":
        named = ", ".join(
            f"{change.case_id} ({_unscored_in(change)})" for change in compared.unmeasured
        )
        return (
            f"Can't say: {plural(len(compared.unmeasured), 'case')} with nothing scored: {named}."
        )
    if compared.finding == "worse":
        named = ", ".join(change.case_id for change in compared.regressed)
        where = f"{plural(len(compared.regressed), 'case')} got worse beyond noise: {named}"
        return f"Hold: {where}." if compared.regressed else "Hold: worse overall beyond noise."
    improved = compared.improved
    better = f" {plural(len(improved), 'case')} got better beyond noise." if improved else ""
    if compared.finding == "better":
        return f"Ship: better overall beyond noise.{better}"
    value, trials = compared.overall.value, compared.trials_to_tell
    settle = ""
    if value and trials is not None:
        settle = (
            f" The overall change is within noise at this size; {plural(trials, 'trial')} per case "
            f"would tell {gap(value)} from noise."
        )
    return f"Ship: nothing got worse beyond noise.{better}{settle}"


def _unscored_in(change: Change) -> str:
    """Which run scored nothing for the case: the baseline, the candidate, or both."""
    sides = [
        side
        for side, rate in (
            ("baseline", change.difference.baseline),
            ("candidate", change.difference.candidate),
        )
        if rate.value is None
    ]
    return " and ".join(sides)
