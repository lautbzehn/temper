"""What a run produces, and how it is kept: a folder written as the run happens.

Answers go in `results.jsonl`, one trial per line, with the request, the
completion, its cost, and every grade. Attempts that never produced an answer
go in `errors.jsonl` with their reason, so plumbing trouble never shares a
column with wrong answers. A live run also keeps `recording.jsonl`, which the
replay provider plays back, and `manifest.json` says what ran, on what, and when.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from temper.errors import RunError, UnreadableFileError
from temper.files import read_text
from temper.graders import Grade
from temper.providers import Completion, Recording, Request, Slot, Status
from temper.suite import Closed, Count

if TYPE_CHECKING:
    from collections.abc import Iterator

Record = TypeVar("Record", bound=BaseModel)
FailureKind = Literal["timeout", "provider", "served-model", "budget"]


class RunOptions(Closed):
    """How a run is driven: how many trials, how many at once, and what it may not exceed."""

    trials: Count | None = None
    concurrency: Count = 8
    time_limit_s: float = Field(default=120.0, gt=0)
    attempts: Count = 4
    budget_usd: float | None = Field(default=None, gt=0)
    backoff_s: float = Field(default=1.0, gt=0)
    replay: Path | None = None


class Retry(BaseModel):
    """One try that didn't answer, and how long the runner waited before the next."""

    model_config = ConfigDict(frozen=True)

    attempt: int
    reason: str
    waited_s: float


class TrialResult(BaseModel):
    """One answered trial: what was asked, what came back, what it cost, and how it graded."""

    model_config = ConfigDict(frozen=True)

    request: Request
    completion: Completion
    grades: tuple[Grade, ...]
    latency_ms: float
    cost_usd: float | None = None
    attempts: int = 1
    retries: tuple[Retry, ...] = ()

    @property
    def case_id(self) -> str:
        """The case this trial belongs to."""
        return self.request.case_id

    @property
    def trial(self) -> int:
        """Which trial of the case this is, counting from 1."""
        return self.request.trial

    @property
    def status(self) -> Status:
        """Whether the answer was complete, cut short, or refused."""
        return self.completion.status

    @property
    def answer(self) -> str:
        """The answer's text."""
        return self.completion.text

    @property
    def passed(self) -> bool:
        """Whether every check passed."""
        return all(grade.passed for grade in self.grades)


class TrialFailure(BaseModel):
    """One trial that never produced an answer, and why. Not a wrong answer: a missing one."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    trial: int
    kind: FailureKind
    reason: str
    attempts: int
    retries: tuple[Retry, ...] = ()
    cost_usd: float | None = None
    at: datetime


class Manifest(BaseModel):
    """What was run, on what, and when: enough to resume it, and to tell two runs apart later."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    suite: str
    suite_path: Path | None
    fingerprint: str
    provider: str
    model: str | None
    charges: bool
    case_ids: tuple[str, ...]
    trials: int
    options: RunOptions
    temper_version: str
    python_version: str
    priced_on: str
    started_at: datetime
    finished_at: datetime | None = None
    resumed: int = 0
    spent_usd: float | None = None

    @property
    def slots(self) -> list[Slot]:
        """Every (case, trial) the run is to answer, in suite order."""
        return [
            (case_id, trial) for case_id in self.case_ids for trial in range(1, self.trials + 1)
        ]


class Run(BaseModel):
    """A run as kept: its manifest, every answered trial in suite order, and every failure."""

    model_config = ConfigDict(frozen=True)

    manifest: Manifest
    results: tuple[TrialResult, ...]
    failures: tuple[TrialFailure, ...] = ()

    @property
    def scored(self) -> tuple[TrialResult, ...]:
        """The trials a pass rate is drawn from: complete answers only."""
        return tuple(result for result in self.results if result.status == "complete")

    @property
    def trials_passed(self) -> int:
        """How many scored trials passed every check."""
        return sum(result.passed for result in self.scored)

    @property
    def cost_usd(self) -> float | None:
        """What every attempt cost at list price, failures included, or None if none was priced."""
        attempts: list[TrialResult | TrialFailure] = [*self.results, *self.failures]
        priced = [attempt.cost_usd for attempt in attempts if attempt.cost_usd is not None]
        return sum(priced) if priced else None

    @property
    def missing(self) -> list[Slot]:
        """The (case, trial) slots with no answer yet, in suite order."""
        answered = {(result.case_id, result.trial) for result in self.results}
        return [slot for slot in self.manifest.slots if slot not in answered]

    def count(self, status: Status) -> int:
        """How many answers have the given status."""
        return sum(result.status == status for result in self.results)

    def by_case(self) -> dict[str, list[TrialResult]]:
        """Each case's trials, in suite order."""
        grouped: dict[str, list[TrialResult]] = {case_id: [] for case_id in self.manifest.case_ids}
        for result in self.results:
            grouped[result.case_id].append(result)
        return grouped


class RunFolder:
    """A run on disk, written as it happens, so an interrupted run keeps every answer it got."""

    def __init__(
        self,
        path: Path,
        manifest: Manifest,
        results: list[TrialResult],
        failures: list[TrialFailure],
    ) -> None:
        self.path = path
        self.manifest = manifest
        self._results = results
        self._failures = failures

    @classmethod
    def start(cls, root: Path, manifest: Manifest) -> Self:
        """Make the run's folder under `root` and write its manifest."""
        folder = cls(root / manifest.run_id, manifest, [], [])
        folder.path.mkdir(parents=True)
        folder._write_manifest()
        return folder

    @classmethod
    def open(cls, path: Path) -> Self:
        """Read a kept run back.

        Raises:
            RunError: the folder isn't a run Temper can read.
        """
        try:
            manifest = Manifest.model_validate_json(read_text(path / "manifest.json"))
            results = list(_lines(path / "results.jsonl", TrialResult))
            failures = list(_lines(path / "errors.jsonl", TrialFailure))
        except UnreadableFileError as error:
            raise RunError(f"{str(path)!r} isn't a run Temper can read: {error}") from None
        except ValidationError as error:
            raise RunError(f"{str(path)!r} holds a record Temper can't read: {error}") from None
        return cls(path, manifest, results, failures)

    @property
    def answered(self) -> frozenset[Slot]:
        """The (case, trial) slots that already have an answer."""
        return frozenset((result.case_id, result.trial) for result in self._results)

    def add(self, result: TrialResult) -> None:
        """Keep an answered trial, and record its completion when the run spent money on it."""
        self._results.append(result)
        _append(self.path / "results.jsonl", result)
        if self.manifest.charges:
            _append(self.path / "recording.jsonl", Recording.of(result.request, result.completion))

    def add_failure(self, failure: TrialFailure) -> None:
        """Keep a failed attempt."""
        self._failures.append(failure)
        _append(self.path / "errors.jsonl", failure)

    def resume(self) -> None:
        """Note that the run is being picked up again."""
        self.manifest = self.manifest.model_copy(
            update={"resumed": self.manifest.resumed + 1, "finished_at": None}
        )
        self._write_manifest()

    def finish(self, spent_usd: float) -> None:
        """Note when the run ended, and what its budget counted as spent, on top of earlier runs."""
        spent = (self.manifest.spent_usd or 0.0) + spent_usd
        update = {"finished_at": datetime.now(UTC), "spent_usd": spent}
        self.manifest = self.manifest.model_copy(update=update)
        self._write_manifest()

    def run(self) -> Run:
        """Everything kept so far, results in suite order."""
        order = {slot: index for index, slot in enumerate(self.manifest.slots)}
        results = sorted(self._results, key=lambda result: order[(result.case_id, result.trial)])
        return Run(manifest=self.manifest, results=tuple(results), failures=tuple(self._failures))

    def _write_manifest(self) -> None:
        text = self.manifest.model_dump_json(indent=2) + "\n"
        (self.path / "manifest.json").write_text(text, encoding="utf-8")


def _append(path: Path, record: BaseModel) -> None:
    with path.open("a", encoding="utf-8") as lines:
        lines.write(record.model_dump_json() + "\n")


def _lines(path: Path, kind: type[Record]) -> Iterator[Record]:
    if not path.exists():
        return
    for line in read_text(path).splitlines():
        if line.strip():
            yield kind.model_validate_json(line)
