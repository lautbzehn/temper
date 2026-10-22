"""The run summary people read in the terminal, and the estimate a dry run prints instead."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from temper.pricing import price_of
from temper.runner import worst_case_usd

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from rich.console import Console

    from temper.results import Run, RunOptions, TrialFailure, TrialResult
    from temper.suite import Suite


def plural(count: int, noun: str) -> str:
    """`3 cases`, `1 case`."""
    return f"{count} {noun}{'' if count == 1 else 's'}"


def render_run(run: Run, console: Console) -> None:
    """Print one line per case, then the totals and what the run cost."""
    manifest = run.manifest
    model = f" {manifest.model}" if manifest.model else ""
    console.print(
        Text.assemble(
            (manifest.suite, "bold"),
            f" · {manifest.provider}{model} · {plural(len(manifest.case_ids), 'case')}",
            f" × {plural(manifest.trials, 'trial')}",
        ),
        end="\n\n",
    )

    failures = _by_case(run.failures)
    table = Table(box=None, pad_edge=False, padding=(0, 3, 0, 0), header_style="dim")
    table.add_column("Case")
    table.add_column("Passed", justify="right")
    table.add_column("Notes")
    for case_id, results in run.by_case().items():
        scored = [result for result in results if result.status == "complete"]
        passed = sum(result.passed for result in scored)
        table.add_row(
            Text(case_id),
            Text(f"{passed}/{len(scored)}", style=_tone(passed, len(scored))),
            Text(_notes(results, failures.get(case_id, [])), style="dim"),
        )
    console.print(table)
    console.print()

    scored_total = len(run.scored)
    rate = f" ({run.trials_passed / scored_total:.0%})" if scored_total else ""
    extras = [
        f"{run.count('truncated')} truncated" if run.count("truncated") else "",
        f"{run.count('refused')} refused" if run.count("refused") else "",
        f"{plural(len(run.failures), 'attempt')} failed, not scored" if run.failures else "",
    ]
    console.print(
        Text.assemble(
            (f"{run.trials_passed} of {plural(scored_total, 'scored trial')} passed{rate}", "bold"),
            "".join(f" · {extra}" for extra in extras if extra),
        )
    )
    if run.cost_usd is not None:
        spent = f"${run.cost_usd:.4f} spent"
        if not manifest.charges:
            spent = f"${run.cost_usd:.4f} at list price, nothing spent"
        console.print(Text(spent, style="dim"))


def render_estimate(
    suite: Suite,
    estimates: Mapping[str, int],
    options: RunOptions,
    console: Console,
    *,
    charges: bool,
) -> None:
    """Print what a run would cost at most, case by case, without running it."""
    trials = options.trials or suite.trials
    console.print(
        Text.assemble((suite.name, "bold"), f" · dry run · {plural(trials, 'trial')} per case")
    )
    console.print()

    table = Table(box=None, pad_edge=False, padding=(0, 3, 0, 0), header_style="dim")
    table.add_column("Case")
    table.add_column("Input tokens", justify="right")
    table.add_column("At most, per trial", justify="right")
    total = 0.0
    for case in suite.cases:
        worst = worst_case_usd(suite, estimates.get(case.id, 0))
        total += worst * trials
        table.add_row(case.id, str(estimates.get(case.id, 0)), f"${worst:.4f}")
    console.print(table)
    console.print()

    if not charges:
        provider = "replay" if options.replay else suite.target.provider
        console.print(
            Text(f"The {provider} provider answers for free; nothing to spend.", style="dim")
        )
        return
    if suite.target.model and price_of(suite.target.model) is None:
        console.print(Text(f"No list price for model {suite.target.model!r}.", style="yellow"))
    console.print(
        Text.assemble(
            (f"At most ${total:.4f} for {plural(trials * len(suite.cases), 'trial')}", "bold"),
            f", with every answer priced at the {suite.target.max_tokens}-token ceiling.",
        )
    )


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


def _notes(results: Sequence[TrialResult], failures: Sequence[TrialFailure]) -> str:
    """What a reader should know about a case beyond its pass count, briefly."""
    notes: list[str] = []
    first_miss = next(
        (
            f"trial {result.trial}: {grade.reason}"
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
