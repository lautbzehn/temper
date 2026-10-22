"""The run summary people read in the terminal."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from pathlib import Path

    from rich.console import Console

    from temper.results import Run, TrialResult


def plural(count: int, noun: str) -> str:
    """`3 cases`, `1 case`."""
    return f"{count} {noun}{'' if count == 1 else 's'}"


def render_run(run: Run, folder: Path, console: Console) -> None:
    """Print one line per case, then the totals and where the run was kept."""
    manifest = run.manifest
    console.print(
        Text.assemble(
            (manifest.suite, "bold"),
            f" · {manifest.provider} · {plural(manifest.cases, 'case')}",
            f" × {plural(manifest.trials, 'trial')}",
        ),
        end="\n\n",
    )

    table = Table(box=None, pad_edge=False, padding=(0, 3, 0, 0), header_style="dim")
    table.add_column("Case")
    table.add_column("Passed", justify="right")
    table.add_column("First failure")
    for case_id, results in run.by_case().items():
        passed = sum(result.passed for result in results)
        table.add_row(
            Text(case_id),
            Text(f"{passed}/{len(results)}", style=_tone(passed, len(results))),
            Text(_first_failure(results), style="dim"),
        )
    console.print(table)
    console.print()

    total = len(run.results)
    console.print(
        Text.assemble(
            (f"{run.passed} of {plural(total, 'trial')} passed", "bold"),
            f" ({run.passed / total:.0%}) · kept in {folder}",
        )
    )


def _tone(passed: int, total: int) -> str:
    if passed == total:
        return "green"
    if passed == 0:
        return "red"
    return "yellow"


def _first_failure(results: list[TrialResult]) -> str:
    for result in results:
        for grade in result.grades:
            if not grade.passed:
                return f"trial {result.trial}: {grade.reason}"
    return ""
