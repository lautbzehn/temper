"""The Dunder Mifflin story, replayed from its recording: free, offline, and the same every time.

The suite, both prompts, and a recording of one real run with each ship
with Temper. Replaying them puts every case through the harness again,
grades every answer again in code, and takes every verdict from the
recording, so the demo needs no key and spends nothing. A recording that no
longer matches what would be asked is refused, trial by trial, rather than
quietly answered.
"""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from temper.comparison import compare
from temper.loading import load_suite
from temper.planning import providers_for
from temper.results import RunOptions
from temper.runner import run_suite

if TYPE_CHECKING:
    from temper.comparison import Comparison
    from temper.results import Run
    from temper.suite import Suite

HERE: Final = Path(__file__).parent
SUITE: Final = HERE / "suite.yaml"
TIDY_UP: Final = HERE / "dwights-tidy-up.md"
RECORDINGS: Final = HERE / "recordings"


@dataclass(frozen=True, slots=True)
class Story:
    """Both runs of the story, as replayed, and what comparing them found."""

    baseline: Run
    candidate: Run

    @property
    def comparison(self) -> Comparison:
        """Dwight's tidy-up set against the prompt it replaced."""
        return compare(self.baseline, self.candidate)


async def replay(out: Path) -> Story:
    """Replay both runs of the story into folders under `out`.

    Raises:
        SuiteError: the packaged suite no longer loads.
        ProviderError: a recording can't be read.
    """
    suite = load_suite(SUITE)
    baseline = RunOptions(replay=RECORDINGS / "baseline.jsonl")
    candidate = RunOptions(replay=RECORDINGS / "dwights-tidy-up.jsonl", system=TIDY_UP)
    return Story(
        await _replay(suite, baseline, out / "baseline"),
        await _replay(suite, candidate, out / "dwights-tidy-up"),
    )


async def _replay(suite: Suite, options: RunOptions, out: Path) -> Run:
    async with aclosing(providers_for(suite, options)) as providers:
        return await run_suite(suite, providers, out=out, options=options)
