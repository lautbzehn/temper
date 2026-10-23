"""The `temper` command line: a thin layer over the library, so all it does is importable too."""

from __future__ import annotations

import asyncio
import tempfile
from contextlib import aclosing, contextmanager
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer
from rich.console import Console

from temper import __version__, calibration, comparison
from temper.demo import replay as replay_story
from temper.doctor import examine
from temper.errors import PluginError, ProviderError, RunError, SuiteError
from temper.labeling import label_run
from temper.labels import Labels
from temper.loading import load_suite
from temper.planning import estimate_suite, plan_run, providers_for
from temper.results import RunFolder, RunOptions
from temper.runner import complete_run, reopen_run, start_run
from temper.scorecard import build_scorecard
from temper.summary import (
    render_calibration,
    render_checkup,
    render_comparison,
    render_estimate,
    render_run,
)
from temper.wording import plural

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from temper.planning import Plan, Providers
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
RunDir = Annotated[Path, typer.Argument(help="A kept run's folder.", show_default=False)]

INTERRUPTED = 130
INCOMPLETE = 2
HELD = 3
UNWELL = 1


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
    concurrency: Annotated[int, typer.Option(min=1, help="Most requests in flight at once.")] = 8,
    time_limit: Annotated[
        float,
        typer.Option("--time-limit", min=1, help="Seconds one request may take, retries included."),
    ] = 120.0,
    attempts: Annotated[
        int, typer.Option(min=1, help="Tries per request before giving up on a passing problem.")
    ] = 4,
    budget: Annotated[
        float | None, typer.Option("--budget", min=0.01, help="Dollars the run may spend.")
    ] = None,
    replay: Annotated[
        Path | None,
        typer.Option(
            "--replay",
            help="Answer from this recording instead of the suite's provider. Verdicts it "
            "holds are replayed too; any it lacks are judged live.",
        ),
    ] = None,
    system: Annotated[
        Path | None,
        typer.Option(
            "--system",
            help="Answer with this system prompt instead of the suite's, to compare two "
            "prompts on the same cases.",
        ),
    ] = None,
    out_dir: Annotated[Path, typer.Option("--out", help="Where each run is kept.")] = Path("runs"),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Say what it would cost; don't run.")
    ] = False,
) -> None:
    """Run every case in a suite, grade the answers, and keep the results.

    Exits 0 when every trial was answered, and 2 when some weren't, in which
    case `temper resume` can try them again.
    """
    options = RunOptions(
        trials=trials,
        concurrency=concurrency,
        time_limit_s=time_limit,
        attempts=attempts,
        budget_usd=budget,
        replay=replay,
        system=system,
    )
    with _plain_errors():
        loaded = load_suite(suite)
        providers = providers_for(loaded, options)
    if dry_run:
        _estimate(loaded, providers, options)
        return

    def fresh(plan: Plan) -> RunFolder:
        _prepare(out_dir)
        return start_run(plan, out=out_dir)

    _drive(
        loaded, providers, options, fresh, before="run stopped before it began, so nothing was kept"
    )


@app.command()
def resume(folder: RunDir) -> None:
    """Pick up a kept run, answering only the trials that still have no answer."""
    with _plain_errors():
        loaded, opened = reopen_run(folder)
        providers = providers_for(loaded, opened.manifest.options)

    def picked_up(_plan: Plan) -> RunFolder:
        opened.resume()
        return opened

    _drive(loaded, providers, opened.manifest.options, picked_up, before="the run wasn't picked up")


@app.command()
def label(folder: RunDir) -> None:
    """Label a kept run's judged answers by hand, blind to the judge, so it can be calibrated."""
    with _plain_errors():
        loaded, opened = reopen_run(folder)
        try:
            ask = partial(out.input, markup=False, emoji=False)
            outcome = label_run(loaded, opened.run(), Labels.of(opened.path), out, ask=ask)
        except (KeyboardInterrupt, EOFError):
            _fail("stopped; every label given so far is kept", code=INTERRUPTED)
    if not outcome.total:
        out.print("Nothing to label: every judged answer in this run has a label already.")
    elif outcome.left:
        out.print(
            f"{plural(outcome.labeled, 'label')} added, {outcome.left} to go. "
            f"Pick it up with: temper label {folder}"
        )
    else:
        out.print(
            f"{plural(outcome.labeled, 'label')} added; every judged answer is labeled. "
            f"Next: temper calibrate {folder}"
        )


@app.command()
def calibrate(
    folder: RunDir,
    *,
    labels: Annotated[
        Path | None,
        typer.Option("--labels", help="A labels file to compare with, when not the run's own."),
    ] = None,
) -> None:
    """Measure how often the judge agreed with your labels, and show every disagreement."""
    if labels is not None and not labels.exists():
        _fail(f"no labels file at {str(labels)!r}")
    with _plain_errors():
        loaded, opened = reopen_run(folder)
        done = (Labels(labels) if labels is not None else Labels.of(opened.path)).read()
    if not done:
        _fail(f"no labels to compare with; make some with: temper label {folder}")
    render_calibration(loaded, calibration.calibrate(loaded, opened.run(), done), out)


@app.command()
def compare(
    baseline: Annotated[
        Path, typer.Argument(help="The run to compare against.", show_default=False)
    ],
    candidate: Annotated[Path, typer.Argument(help="The run that may ship.", show_default=False)],
    *,
    fail_on_regression: Annotated[
        bool,
        typer.Option(
            "--fail-on-regression",
            help="Exit 3 when the candidate can't ship: worse beyond noise, or unmeasured. For CI.",
        ),
    ] = False,
) -> None:
    """Set a candidate run against a baseline, case by case, and say whether to ship."""
    with _plain_errors():
        compared = comparison.compare(
            RunFolder.open(baseline).run(), RunFolder.open(candidate).run()
        )
    render_comparison(compared, out)
    if fail_on_regression and not compared.ship:
        raise typer.Exit(HELD)


@app.command()
def scorecard(
    folder: RunDir,
    *,
    baseline: Annotated[
        Path | None, typer.Option("--baseline", help="A run to set this one against.")
    ] = None,
    out_file: Annotated[
        Path | None,
        typer.Option("--out", help="Where to write the page. Defaults to the run's own folder."),
    ] = None,
) -> None:
    """Write a run's scorecard: one HTML file to read, share, or keep beside the run."""
    with _plain_errors():
        run = RunFolder.open(folder).run()
        before = RunFolder.open(baseline).run() if baseline is not None else None
        page = build_scorecard(run, before)
    target = out_file or folder / "scorecard.html"
    _write_page(target, page)
    out.print(f"Wrote {target}", markup=False)


@app.command()
def demo(
    *,
    out_file: Annotated[
        Path, typer.Option("--out", help="Where to write the story's scorecard.")
    ] = Path("temper-demo.html"),
) -> None:
    """Replay the Dunder Mifflin story from its recording: free, offline, and no key needed.

    A support bot's careful prompt, and Dwight's tidier one, each answered
    the same 40 questions five times. The comparison says whether to ship.
    """
    with _plain_errors(), tempfile.TemporaryDirectory() as scratch:
        story = asyncio.run(replay_story(Path(scratch)))
    render_comparison(story.comparison, out)
    _write_page(out_file, build_scorecard(story.candidate, story.baseline))
    out.print()
    out.print(f"Wrote the story's scorecard to {out_file}. Open it in a browser.", markup=False)


@app.command()
def doctor(
    suite: Annotated[
        Path | None,
        typer.Argument(
            help="A suite whose models to probe; Temper's own by default.", show_default=False
        ),
    ] = None,
    *,
    out_dir: Annotated[Path, typer.Option("--out", help="Where runs are kept.")] = Path("runs"),
) -> None:
    """Check the wiring: Python, credentials, the API, the runs folder, and an offline run.

    Nothing is spent: the API is only asked to count tokens. Exits 1 when a check fails.
    """
    loaded: Suite | None = None
    if suite is not None:
        with _plain_errors():
            loaded = load_suite(suite)
    diagnoses = asyncio.run(examine(loaded, out_dir))
    render_checkup(diagnoses, out)
    if not all(diagnosis.ok for diagnosis in diagnoses):
        raise typer.Exit(UNWELL)


@contextmanager
def _plain_errors() -> Iterator[None]:
    """Turn the errors a person can act on into plain lines and an exit code of 1."""
    try:
        yield
    except SuiteError as error:
        _fail(*error.lines())
    except (PluginError, ProviderError, RunError) as error:
        _fail(str(error))


def _write_page(target: Path, page: str) -> None:
    """Write a scorecard, or say plainly why it can't be written."""
    try:
        target.write_text(page, encoding="utf-8")
    except OSError as error:
        _fail(f"can't write the scorecard to {str(target)!r}: {error.strerror}")


def _prepare(out_dir: Path) -> None:
    """Make sure the run can be kept before spending time on it."""
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        _fail(f"can't keep runs in {str(out_dir)!r}: {error.strerror}")


def _estimate(suite: Suite, providers: Providers, options: RunOptions) -> None:
    """Count every request's tokens and print what the run could cost, at most."""

    async def counted() -> Plan:
        async with aclosing(providers):
            return await estimate_suite(suite, providers, options)

    with _plain_errors():
        plan = asyncio.run(counted())
    render_estimate(plan, options, out)


def _drive(
    suite: Suite,
    providers: Providers,
    options: RunOptions,
    folder_once_planned: Callable[[Plan], RunFolder],
    *,
    before: str,
) -> None:
    """Plan the run, open its folder, and answer it, then print how it went and exit to match.

    All of it happens in one event loop and closes the providers at the end,
    so a connection the preflight opened is still good when the trials need it.
    """
    folder: RunFolder | None = None

    async def driven() -> Run:
        nonlocal folder
        async with aclosing(providers):
            plan = await plan_run(suite, providers, options)
            folder = folder_once_planned(plan)
            out.print(f"Keeping this run in {folder.path}", style="dim")
            return await complete_run(plan, folder)

    try:
        finished = asyncio.run(driven())
    except SuiteError as error:
        _fail(*error.lines())
    except ProviderError as error:
        _fail(f"{before}: {error}")
    except KeyboardInterrupt:
        _fail(_interrupted(folder), code=INTERRUPTED)
    except Exception:
        if folder is not None:
            err.print(f"Stopped by an unexpected error. What finished is kept. {_pick_up(folder)}")
        raise
    render_run(finished, out)
    if finished.missing and folder is not None:
        err.print(
            f"Try the unanswered trials again with: temper resume {folder.path}", style="yellow"
        )
        raise typer.Exit(INCOMPLETE)


def _interrupted(folder: RunFolder | None) -> str:
    if folder is None:
        return "interrupted before the run began, so nothing was kept"
    return f"interrupted; what finished is kept. {_pick_up(folder)}"


def _pick_up(folder: RunFolder) -> str:
    return f"Pick it up with: temper resume {folder.path}"


def _fail(*lines: str, code: int = 1) -> NoReturn:
    for line in lines:
        err.print(line, style="red", markup=False)
    raise typer.Exit(code)
