"""What a run produced, and how it is kept: a manifest plus one JSON line per trial."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from temper.graders import Grade

if TYPE_CHECKING:
    from pathlib import Path


class TrialResult(BaseModel):
    """One answer to one case, and how each of its checks graded it."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    trial: int
    answer: str
    model: str
    latency_ms: float
    grades: tuple[Grade, ...]

    @property
    def passed(self) -> bool:
        """Whether every check passed."""
        return all(grade.passed for grade in self.grades)


class Manifest(BaseModel):
    """What was run, on what, and when: enough to tell two runs apart later."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    suite: str
    fingerprint: str
    provider: str
    model: str | None
    cases: int
    trials: int
    temper_version: str
    python_version: str
    started_at: datetime
    finished_at: datetime


class Run(BaseModel):
    """A finished run: its manifest, and every trial's result in suite order."""

    model_config = ConfigDict(frozen=True)

    manifest: Manifest
    results: tuple[TrialResult, ...]

    @property
    def trials_passed(self) -> int:
        """How many trials passed every check."""
        return sum(result.passed for result in self.results)

    def by_case(self) -> dict[str, list[TrialResult]]:
        """Each case's trials, in the order the cases first appear."""
        grouped: dict[str, list[TrialResult]] = {}
        for result in self.results:
            grouped.setdefault(result.case_id, []).append(result)
        return grouped


def write_run(run: Run, root: Path) -> Path:
    """Keep a run in its own folder under `root`, and return that folder.

    The folder holds `manifest.json` and `results.jsonl`, one trial per line,
    so later tools can stream results without loading them all at once.
    """
    folder = root / run.manifest.run_id
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(
        run.manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    with (folder / "results.jsonl").open("w", encoding="utf-8") as lines:
        lines.writelines(result.model_dump_json() + "\n" for result in run.results)
    return folder
