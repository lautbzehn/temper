"""The `temper` command line: a thin layer over the library, so all it does is importable too."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer
from rich.console import Console

from temper import __version__
from temper.errors import ProviderError, SuiteError
from temper.loading import load_suite
from temper.providers import build_provider
from temper.results import write_run
from temper.runner import run_suite
from temper.summary import plural, render_run

if TYPE_CHECKING:
    from temper.providers import Provider
    from temper.results import Run
    from temper.suite import Suite

app = typer.Typer(
    help="Test AI features the way you test code, and know when a difference is real.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
out = Console(highlight=False, soft_wrap=True)
err = Console(stderr=True, highlight=False, soft_wrap=True)

SuiteFile = Annotated[Path, typer.Argument(help="The suite file to use.", show_default=False)]


def _show_version(*, value: bool) -> None:
    if value:
        out.print(f"temper {__version__}")
        raise typer.Exit


@app.callback()
def main(
    *,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the version and exit.", callback=_show_version),
    ] = False,
) -> None:
    """Test AI features the way you test code, and know when a difference is real."""


@app.command()
def validate(suite: SuiteFile) -> None:
    """Check a suite file and report every problem with its line number."""
    loaded = _load(suite)
    checks = sum(len(case.checks) for case in loaded.cases)
    summary = f"{plural(len(loaded.cases), 'case')}, {plural(checks, 'check')}"
    out.print(f"✓ {suite} is valid: {summary}", style="green", markup=False)


@app.command()
def run(
    suite: SuiteFile,
    *,
    trials: Annotated[
        int | None, typer.Option(min=1, help="Trials per case. Defaults to the suite's own.")
    ] = None,
    concurrency: Annotated[int, typer.Option(min=1, help="Most trials in flight at once.")] = 8,
    out_dir: Annotated[Path, typer.Option("--out", help="Where each run is kept.")] = Path("runs"),
) -> None:
    """Run every case in a suite, grade the answers, and keep the results."""
    loaded = _load(suite)
    provider = build_provider(loaded.target, suite.parent)
    finished = _execute(loaded, provider, trials=trials, concurrency=concurrency)
    render_run(finished, write_run(finished, out_dir), out)


def _load(path: Path) -> Suite:
    try:
        return load_suite(path)
    except SuiteError as error:
        _fail(*error.lines())


def _execute(suite: Suite, provider: Provider, *, trials: int | None, concurrency: int) -> Run:
    try:
        return asyncio.run(run_suite(suite, provider, trials=trials, concurrency=concurrency))
    except ExceptionGroup as group:
        failures = group.subgroup(ProviderError)
        if failures is None:
            raise
        _fail(*(f"run stopped: {failure}" for failure in failures.exceptions))


def _fail(*lines: str) -> NoReturn:
    for line in lines:
        err.print(line, style="red", markup=False)
    raise typer.Exit(1)
