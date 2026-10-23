"""What people read in the terminal: a run, a dry run's estimate, a calibration, a comparison."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from temper.calibration import FLOOR, KAPPA, TRUSTED
from temper.planning import charged_models
from temper.pricing import price_of
from temper.wording import change_span, dollars, gap, percent, plural, points, span

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rich.console import Console, JustifyMethod

    from temper.calibration import Calibration
    from temper.comparison import Comparison
    from temper.doctor import Finding
    from temper.planning import Plan
    from temper.results import Manifest, Run, RunOptions, TrialFailure, TrialResult
    from temper.stats import Difference, Direction, Rate
    from temper.suite import Suite


def render_run(run: Run, console: Console) -> None:
    """Print one line per case with its likely rate, then the totals, the noise, and the cost."""
    manifest = run.manifest
    console.print(Text.assemble((manifest.suite, "bold"), f" · {_described(manifest)}"), end="\n\n")

    failures = _by_case(run.failures)
    rates = run.rates
    table = _table("Case", ("Passed", "right"), "Likely rate", "Notes")
    for case_id, results in run.by_case().items():
        rate = rates[case_id]
        table.add_row(
            Text(case_id),
            Text(f"{rate.passed}/{rate.scored}", style=_tone(rate.passed, rate.scored)),
            Text(span(rate.interval) if rate.scored else "", style="dim"),
            Text(_notes(rate, results, failures.get(case_id, [])), style="dim"),
        )
    console.print(table)
    console.print()

    rate = run.rate
    likely = (
        f" ({percent(rate.value)}, likely {span(rate.interval)})" if rate.value is not None else ""
    )
    extras = [
        f"{run.count('truncated')} truncated" if run.count("truncated") else "",
        f"{run.count('refused')} refused" if run.count("refused") else "",
        f"{run.without_verdict} with no verdict" if run.without_verdict else "",
        f"{plural(len(run.failures), 'attempt')} failed, not scored" if run.failures else "",
    ]
    console.print(
        Text.assemble(
            (f"{rate.passed} of {plural(rate.scored, 'scored trial')} passed{likely}", "bold"),
            _joined(extras),
        )
    )
    if rate.scored:
        flaky = f" {plural(len(run.flaky), 'flaky case')}: passed some trials, failed others."
        console.print(Text(_noise(rate) + (flaky if run.flaky else ""), style="dim"))
    if (cost := _cost_line(run)) is not None:
        console.print(Text(cost, style="dim"))


def render_comparison(compared: Comparison, console: Console) -> None:
    """Print each case's change, the overall change against the noise, and the call."""
    console.print(
        Text.assemble(
            (compared.baseline.suite, "bold"), f" · {plural(len(compared.changes), 'case')}"
        )
    )
    for role, manifest in (("baseline", compared.baseline), ("candidate", compared.candidate)):
        console.print(Text(f"{role:<10}{manifest.run_id} · {_described(manifest)}", style="dim"))
    console.print()

    table = _table("Case", ("Baseline", "right"), ("Candidate", "right"), "Change")
    for change in compared.changes:
        difference = change.difference
        table.add_row(
            Text(change.case_id),
            _count(difference.baseline),
            _count(difference.candidate),
            Text(_changed(difference), style=_shade(difference.direction)),
        )
    console.print(table)
    console.print()

    overall = compared.overall
    before, after, value = overall.baseline.value, overall.candidate.value, overall.value
    if before is None or after is None or value is None:
        console.print(Text("Nothing to compare: a run has no scored trials.", "bold"))
        return
    console.print(
        Text.assemble(
            (f"Overall {percent(before)} → {percent(after)}, {points(value)}", "bold"),
            f" (likely {change_span(overall.interval)}). {_noise(overall.baseline)}",
        )
    )
    console.print(Text(_call(compared), style="green" if compared.ship else "red"))


def render_findings(findings: Sequence[Finding], console: Console) -> None:
    """Print each check-up finding on a line, marked fine or not."""
    for finding in findings:
        mark, style = ("✓", "green") if finding.ok else ("✗", "red")
        console.print(Text.assemble((f"{mark} {finding.name}: ", style), finding.note))


def _described(manifest: Manifest) -> str:
    """`claude claude-sonnet-5-5 · judge claude-opus-5-5 · 5 cases × 3 trials`."""
    model = f" {manifest.model}" if manifest.model else ""
    judged = f" · judge {manifest.judge}" if manifest.judge else ""
    cases = plural(len(manifest.case_ids), "case")
    return f"{manifest.provider}{model}{judged} · {cases} × {plural(manifest.trials, 'trial')}"


def _noise(rate: Rate) -> str:
    return f"Differences under {gap(rate.noise_floor)} are within noise at this size."


def _count(rate: Rate) -> Text:
    return Text(f"{rate.passed}/{rate.scored}", style=_tone(rate.passed, rate.scored))


def _changed(difference: Difference) -> str:
    if difference.value is None:
        return "nothing scored"
    beyond = f", {difference.direction} beyond noise" if difference.direction else ""
    return f"{points(difference.value)}{beyond}"


def _shade(direction: Direction | None) -> str:
    return {"better": "green", "worse": "red", None: "dim"}[direction]


def _call(compared: Comparison) -> str:
    """The verdict in a sentence: hold for anything worse beyond noise, ship otherwise."""
    if compared.finding == "worse":
        named = ", ".join(change.case_id for change in compared.regressed)
        where = f"{plural(len(compared.regressed), 'case')} got worse beyond noise: {named}"
        return f"Hold: {where}." if compared.regressed else "Hold: worse overall beyond noise."
    better = (
        f" {plural(len(compared.improved), 'case')} got better beyond noise."
        if compared.improved
        else ""
    )
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


def render_estimate(plan: Plan, options: RunOptions, console: Console) -> None:
    """Print what a run would cost at most, case by case, without running it."""
    suite = plan.suite
    trials = options.trials or suite.trials
    console.print(
        Text.assemble((suite.name, "bold"), f" · dry run · {plural(trials, 'trial')} per case")
    )
    console.print()

    columns: list[str | tuple[str, JustifyMethod]] = ["Case", ("Input tokens", "right")]
    if suite.judged:
        columns.append(("Judge calls", "right"))
    table = _table(*columns, ("At most, per trial", "right"))
    total = 0.0
    for case in suite.cases:
        worst = plan.worst_trial_usd(case)
        total += worst * trials
        cells = [case.id, str(plan.estimates.answers.get(case.id, 0))]
        if suite.judged:
            cells.append(str(len(case.judged)))
        table.add_row(*cells, dollars(worst))
    console.print(table)
    console.print()

    if not plan.providers.charges:
        provider = "replay" if options.replay else suite.target.provider
        console.print(
            Text(f"The {provider} provider answers for free; nothing to spend.", style="dim")
        )
        return
    for model in charged_models(suite, plan.providers):
        if model is not None and price_of(model) is None:
            console.print(Text(f"No list price for model {model!r}.", style="yellow"))
    if options.replay and suite.judged:
        slots = sum(len(case.judged) for case in suite.cases) * trials
        held = plan.estimates.verdicts_on_record
        console.print(
            Text(
                f"Answers replay for free. {held} of {plural(slots, 'verdict')} are in the "
                "recording; the rest will be judged live.",
                style="dim",
            )
        )
        if held == slots:
            console.print(Text("Nothing to spend.", style="bold"))
            return
    verdicts = " and every verdict at the judge's" if suite.judged else ""
    console.print(
        Text.assemble(
            (f"At most {dollars(total)} for {plural(trials * len(suite.cases), 'trial')}", "bold"),
            f", with every answer priced at the {suite.target.max_tokens}-token ceiling{verdicts}.",
        )
    )


def render_calibration(suite: Suite, calibration: Calibration, console: Console) -> None:
    """Print how the judge and the person agreed, property by property, and every disagreement."""
    console.print(
        Text.assemble(
            (suite.name, "bold"),
            f" · judge {suite.judge.model} · {plural(calibration.labeled, 'label')} met a verdict",
        ),
        end="\n\n",
    )
    table = _table("Property", ("Agreed", "right"))
    for property_, (agreed, labeled) in calibration.by_property.items():
        table.add_row(Text(property_), Text(f"{agreed} of {labeled}", style=_tone(agreed, labeled)))
    console.print(table)
    console.print()

    extras = [
        f"{calibration.without_verdict} with no verdict" if calibration.without_verdict else "",
        f"{calibration.reworded} under a reworded property" if calibration.reworded else "",
        f"{calibration.unmatched} about answers not in this run" if calibration.unmatched else "",
    ]
    agreement = calibration.agreement
    if agreement is None:
        console.print(Text.assemble(("No label met a verdict", "bold"), _joined(extras)))
        return
    kappa = f" · kappa {calibration.kappa:.2f}" if calibration.kappa is not None else ""
    console.print(
        Text.assemble(
            (f"Agreement {agreement:.0%} ({calibration.agreed} of {calibration.labeled})", "bold"),
            kappa,
            _joined(extras),
        )
    )
    for split in calibration.disagreements:
        console.print(
            Text(
                f'  {split.case_id} trial {split.trial} · "{split.property}" · '
                f"judge: {_CALL[split.judge_passed]}, you: {_CALL[split.label_passed]} · "
                f"the judge said: {split.judge_reason}",
                style="dim",
            )
        )
    console.print()
    bar = f"agreement at {TRUSTED:.0%} or better and kappa at {KAPPA} or better"
    trusted = calibration.trusted
    if trusted is None:
        short = f"Too few labels to say: {calibration.labeled} of the {FLOOR} it takes."
        console.print(Text(short, style="yellow"))
    elif trusted:
        console.print(
            Text(f"Trusted: {plural(FLOOR, 'label')} or more, with {bar}.", style="green")
        )
    else:
        console.print(
            Text(
                f"Not yet trusted: it takes {bar}. Read the disagreements, reword the "
                "property or pick another judge, then run the suite again with --replay "
                "to judge the same answers.",
                style="yellow",
            )
        )


def _table(*columns: str | tuple[str, JustifyMethod]) -> Table:
    """A plain table with the given columns, each a header or a (header, justify) pair."""
    table = Table(box=None, pad_edge=False, padding=(0, 3, 0, 0), header_style="dim")
    for column in columns:
        if isinstance(column, str):
            table.add_column(column)
        else:
            header, justify = column
            table.add_column(header, justify=justify)
    return table


def _cost_line(run: Run) -> str | None:
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


def _joined(extras: Sequence[str]) -> str:
    return "".join(f" · {extra}" for extra in extras if extra)


_CALL = {True: "pass", False: "fail"}


def _by_case(failures: Sequence[TrialFailure]) -> dict[str, list[TrialFailure]]:
    grouped: dict[str, list[TrialFailure]] = {}
    for failure in failures:
        grouped.setdefault(failure.case_id, []).append(failure)
    return grouped


def _tone(passed: int, scored: int) -> str:
    if scored == 0:
        return "dim"
    if passed == scored:
        return "green"
    return "red" if passed == 0 else "yellow"


def _notes(rate: Rate, results: Sequence[TrialResult], failures: Sequence[TrialFailure]) -> str:
    """What a reader should know about a case beyond its pass count, briefly."""
    notes: list[str] = ["flaky"] if rate.flaky else []
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
        notes.append(first_miss)
    notes.extend(
        f"{number} {status}"
        for status in ("truncated", "refused")
        if (number := sum(result.status == status for result in results))
    )
    if failures:
        kinds = ", ".join(sorted({failure.kind for failure in failures}))
        notes.append(f"{plural(len(failures), 'attempt')} failed: {kinds}")
    return " · ".join(notes)
