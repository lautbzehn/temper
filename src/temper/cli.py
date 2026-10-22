"""The `temper` command line: a thin layer over the library, so all it does is importable too."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer
from rich.console import Console

from temper import __version__
from temper.errors import ProviderError, RunError, SuiteError
from temper.loading import load_suite
from temper.results import RunOptions
from temper.runner import (
    complete_run,
    estimate_suite,
    plan_run,
    provider_for,
    reopen_run,
    start_run,
)
from temper.summary import plural, render_estimate, render_run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from temper.providers import Provider
    from temper.results import RunFolder
    from temper.runner import Plan
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
RunDir = Annotated[Path, typer.Argument(help="A kept run's folder.", show_default=False)]

INTERRUPTED = 130
INCOMPLETE = 2


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
    with _plain_errors():
        loaded = load_suite(suite)
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
    time_limit: Annotated[
        float,
        typer.Option("--time-limit", min=1, help="Seconds a trial may take, retries included."),
    ] = 120.0,
    attempts: Annotated[
        int, typer.Option(min=1, help="Tries per trial before giving up on a passing problem.")
    ] = 4,
    budget: Annotated[
        float | None, typer.Option("--budget", min=0.01, help="Dollars the run may spend.")
    ] = None,
    replay: Annotated[
        Path | None,
        typer.Option(
            "--replay", help="Answer from this recording instead of the suite's provider."
        ),
    ] = None,
    out_dir: Annotated[Path, typer.Option("--out", help="Where each run is kept.")] = Path("runs"),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Say what it would cost; don't run.")
    ] = False,
) -> None:
    """Run every case in a suite, grade the answers, and keep the results.

    Exits 0 when every trial was answered, and 2 when some weren't, in which
    case `temper resume` can try them again. The results aren't judged yet.
    """
    options = RunOptions(
        trials=trials,
        concurrency=concurrency,
        time_limit_s=time_limit,
        attempts=attempts,
        budget_usd=budget,
        replay=replay.resolve() if replay else None,
    )
    with _plain_errors():
        loaded = load_suite(suite)
        provider = provider_for(loaded, options)
        if dry_run:
            estimates = asyncio.run(estimate_suite(loaded, provider, options))
            render_estimate(loaded, estimates, options, out, charges=provider.charges)
            return
    plan = _planned(loaded, provider, options, "run stopped before it began, so nothing was kept")
    _prepare(out_dir)
    _finish(loaded, provider, start_run(loaded, provider, out=out_dir, options=options), plan)


@app.command()
def resume(folder: RunDir) -> None:
    """Pick up a kept run, answering only the trials that still have no answer."""
    with _plain_errors():
        loaded, opened = reopen_run(folder)
        provider = provider_for(loaded, opened.manifest.options)
    plan = _planned(loaded, provider, opened.manifest.options, "the run wasn't picked up")
    opened.resume()
    _finish(loaded, provider, opened, plan)


@contextmanager
def _plain_errors() -> Iterator[None]:
    """Turn the errors a person can act on into plain lines and an exit code of 1."""
    try:
        yield
    except SuiteError as error:
        _fail(*error.lines())
    except (ProviderError, RunError) as error:
        _fail(str(error))


def _planned(suite: Suite, provider: Provider, options: RunOptions, otherwise: str) -> Plan:
    """The run's plan, or a plain failure that opens with `otherwise`."""
    try:
        return asyncio.run(plan_run(suite, provider, options))
    except ProviderError as error:
        _fail(f"{otherwise}: {error}")


def _prepare(out_dir: Path) -> None:
    """Make sure the run can be kept before spending time on it."""
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        _fail(f"can't keep runs in {str(out_dir)!r}: {error.strerror}")


def _finish(suite: Suite, provider: Provider, folder: RunFolder, plan: Plan) -> None:
    """Run what the folder still needs, print the summary, and exit with how it went."""
    out.print(f"Keeping this run in {folder.path}", style="dim")
    pick_up = f"Pick it up with: temper resume {folder.path}"
    try:
        finished = asyncio.run(complete_run(suite, provider, folder, plan))
    except KeyboardInterrupt:
        _fail(f"interrupted; what finished is kept. {pick_up}", code=INTERRUPTED)
    except Exception:
        err.print(
            f"Stopped by an unexpected error. What finished is kept. {pick_up}", style="yellow"
        )
        raise
    render_run(finished, out)
    if finished.missing:
        err.print(
            f"Try the unanswered trials again with: temper resume {folder.path}", style="yellow"
        )
        raise typer.Exit(INCOMPLETE)


def _fail(*lines: str, code: int = 1) -> NoReturn:
    for line in lines:
        err.print(line, style="red", markup=False)
    raise typer.Exit(code)
