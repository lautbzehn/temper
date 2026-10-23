"""What people read in the terminal: a run, a dry run's estimate, a calibration, a comparison."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from temper import prose
from temper.calibration import FLOOR, KAPPA, TRUSTED
from temper.planning import charged_models
from temper.pricing import price_of
from temper.wording import dollars, plural, span

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rich.console import Console, JustifyMethod

    from temper.calibration import Calibration
    from temper.comparison import Comparison
    from temper.doctor import Diagnosis
    from temper.planning import Plan
    from temper.results import Run, RunOptions
    from temper.stats import Direction, Rate
    from temper.suite import Suite


def render_run(run: Run, console: Console) -> None:
    """Print one line per case with its likely rate, then the totals, the noise, and the cost."""
    manifest = run.manifest
    console.print(
        Text.assemble((manifest.suite, "bold"), f" · {prose.described(manifest)}"), end="\n\n"
    )

    failures = prose.failures_by_case(run.failures)
    rates = run.rates
    table = _table("Case", ("Passed", "right"), "Likely rate", "Notes")
    for case_id, results in run.by_case().items():
        rate = rates[case_id]
        table.add_row(
            Text(case_id),
            _count(rate),
            Text(span(rate.interval) if rate.scored else "", style="dim"),
            Text(prose.notes(rate, results, failures.get(case_id, [])), style="dim"),
        )
    console.print(table)
    console.print()

    console.print(Text.assemble((prose.tally(run), "bold"), _joined(prose.left_out(run))))
    if run.rate.scored:
        noise = prose.noise(run.rate)
        flaky = prose.flaky(run)
        console.print(Text(f"{noise} {flaky}" if flaky else noise, style="dim"))
    if (cost := prose.cost(run)) is not None:
        console.print(Text(cost, style="dim"))


def render_comparison(compared: Comparison, console: Console) -> None:
    """Print each case's change, the overall change against the noise, and the call."""
    console.print(
        Text.assemble(
            (compared.baseline.suite, "bold"), f" · {plural(len(compared.changes), 'case')}"
        )
    )
    for role, manifest in (("baseline", compared.baseline), ("candidate", compared.candidate)):
        line = f"{role:<10}{manifest.run_id} · {prose.described(manifest)}"
        console.print(Text(line, style="dim"))
    console.print()

    table = _table("Case", ("Baseline", "right"), ("Candidate", "right"), "Change")
    for change in compared.changes:
        difference = change.difference
        table.add_row(
            Text(change.case_id),
            _count(difference.baseline),
            _count(difference.candidate),
            Text(prose.changed(difference), style=_shade(difference.direction)),
        )
    console.print(table)
    console.print()

    for caveat in prose.caveats(compared):
        console.print(Text(caveat, style="yellow"))
    overall = prose.overall(compared)
    if overall is not None:
        console.print(Text.assemble((overall, "bold"), f" {prose.noise_for(compared)}"))
    console.print(Text(prose.verdict(compared), style=_tone_of(compared)))


def render_checkup(diagnoses: Sequence[Diagnosis], console: Console) -> None:
    """Print each of the doctor's diagnoses on a line, marked fine or not."""
    for diagnosis in diagnoses:
        mark, style = ("✓", "green") if diagnosis.ok else ("✗", "red")
        console.print(Text.assemble((f"{mark} {diagnosis.name}: ", style), diagnosis.note))


def _tone_of(compared: Comparison) -> str:
    return {"unmeasured": "yellow", "worse": "red"}.get(compared.finding, "green")


def _count(rate: Rate) -> Text:
    return Text(prose.count(rate), style=_tone(rate.passed, rate.scored))


def _shade(direction: Direction | None) -> str:
    return {"better": "green", "worse": "red", None: "dim"}[direction]


def render_estimate(plan: Plan, options: RunOptions, console: Console) -> None:
    """Print what a run would cost at most, case by case, without running it."""
    suite = plan.suite
    trials = options.trials or suite.trials
    prompt = f" · system {options.system.name}" if options.system is not None else ""
    console.print(
        Text.assemble(
            (suite.name, "bold"), f"{prompt} · dry run · {plural(trials, 'trial')} per case"
        )
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


def _joined(extras: Sequence[str]) -> str:
    return "".join(f" · {extra}" for extra in extras if extra)


_CALL = {True: "pass", False: "fail"}


def _tone(passed: int, scored: int) -> str:
    if scored == 0:
        return "dim"
    if passed == scored:
        return "green"
    return "red" if passed == 0 else "yellow"
