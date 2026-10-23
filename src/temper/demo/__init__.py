"""The Dunder Mifflin story, replayed from its recording: free, offline, and the same every time.

The suite, both prompts, and a recording of one real run with each ship
with Temper. Replaying them puts every case through the harness again and
grades every answer again in code. The recording is the only provider the
replay is given, for the answers and for the judge alike, so nothing in the
demo can reach the API: an answer or a verdict that is no longer on record
is refused and written down as missing, never bought.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from temper.comparison import compare
from temper.loading import load_suite
from temper.planning import Providers
from temper.providers import ReplayProvider
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
    """Both runs of the story as replayed, and the tidy-up set against the prompt it replaced."""

    baseline: Run
    candidate: Run
    comparison: Comparison


async def replay(out: Path) -> Story:
    """Replay both runs of the story into folders under `out`.

    Raises:
        SuiteError: the packaged suite no longer loads.
        ProviderError: a recording can't be read.
    """
    suite = load_suite(SUITE)
    baseline = await _replay(suite, RECORDINGS / "baseline.jsonl", out / "baseline")
    candidate = await _replay(
        suite, RECORDINGS / "dwights-tidy-up.jsonl", out / "dwights-tidy-up", system=TIDY_UP
    )
    return Story(baseline, candidate, compare(baseline, candidate))


async def _replay(suite: Suite, recording: Path, out: Path, *, system: Path | None = None) -> Run:
    recorded = ReplayProvider.from_file(recording)
    providers = Providers(answers=recorded, judge=recorded, recording=recorded)
    options = RunOptions(replay=recording, system=system)
    return await run_suite(suite, providers, out=out, options=options)
