"""What a run produces, and how it is kept: a folder written as the run happens.

Answers go in `results.jsonl`, one trial per line, with the request, the
completion, its cost, and every grade. Attempts that never produced an answer
go in `errors.jsonl` with their reason, so plumbing trouble never shares a
column with wrong answers. A run that spends money also keeps
`recording.jsonl`, every completion it paid for, answers and verdicts alike,
which the replay provider plays back. `manifest.json` says what ran, on what,
and when.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from temper import jsonl
from temper.errors import BadLineError, RunError, UnreadableFileError
from temper.files import read_text
from temper.graders import Answer, Grade
from temper.providers import Completion, Recording, ReplayProvider, Request, Slot, Status
from temper.stats import Rate
from temper.suite import Closed, Count

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from temper.jsonl import Record

FailureKind = Literal["timeout", "provider", "served-model", "budget"]


def _absolute(path: Path) -> Path:
    return path.resolve()


# A file a run reads, held as an absolute path so the run can be resumed from anywhere.
RunFile = Annotated[Path, AfterValidator(_absolute)]


class RunOptions(Closed):
    """How a run is driven: how many trials, how many at once, what it may not exceed.

    `replay` answers from a recording instead of the suite's provider, and
    `system` with another system prompt instead of the suite's own.
    """

    trials: Count | None = None
    concurrency: Count = 8
    time_limit_s: float = Field(default=120.0, gt=0)
    attempts: Count = 4
    budget_usd: float | None = Field(default=None, gt=0)
    backoff_s: float = Field(default=1.0, gt=0)
    replay: RunFile | None = None
    system: RunFile | None = None


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
    def answer(self) -> Answer:
        """The answer as the checks saw it."""
        return Answer(
            text=self.completion.text,
            conversation=self.request.messages,
            latency_ms=self.latency_ms,
            cost_usd=self.cost_usd,
        )

    @property
    def graded(self) -> bool:
        """Whether every check reached a verdict."""
        return all(grade.passed is not None for grade in self.grades)

    @property
    def passed(self) -> bool | None:
        """Whether every check passed, or None while some check has no verdict."""
        return all(grade.passed for grade in self.grades) if self.graded else None

    @property
    def scored(self) -> bool:
        """Whether a pass rate may count this trial: complete, every check having a verdict."""
        return self.status == "complete" and self.graded

    @property
    def verdicts_usd(self) -> float | None:
        """What the judge's verdicts on this trial cost at list price, or None if none was asked."""
        return _priced(grade.cost_usd for grade in self.grades)


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
    judge: str | None = None
    cases_fingerprint: str | None = None
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
        """The trials a pass rate is drawn from: complete answers with a verdict on every check."""
        return tuple(result for result in self.results if result.scored)

    @property
    def trials_passed(self) -> int:
        """How many scored trials passed every check."""
        return sum(result.passed is True for result in self.scored)

    @property
    def rate(self) -> Rate:
        """The run's pass rate: its scored trials pooled."""
        return Rate(self.trials_passed, len(self.scored))

    @property
    def rates(self) -> dict[str, Rate]:
        """Each case's pass rate over its scored trials, in suite order."""
        return {case_id: _rate_of(results) for case_id, results in self.by_case().items()}

    @property
    def flaky(self) -> tuple[str, ...]:
        """The cases whose trials disagreed with each other."""
        return tuple(case_id for case_id, rate in self.rates.items() if rate.flaky)

    @property
    def without_verdict(self) -> int:
        """How many complete answers some check reached no verdict on, so they aren't scored."""
        return sum(result.status == "complete" and not result.graded for result in self.results)

    @property
    def cost_usd(self) -> float | None:
        """What every request cost at list price, verdicts and failures too, or None if unpriced."""
        answers = (result.cost_usd for result in self.results)
        verdicts = (result.verdicts_usd for result in self.results)
        failures = (failure.cost_usd for failure in self.failures)
        return _priced((*answers, *verdicts, *failures))

    @property
    def verdicts_usd(self) -> float | None:
        """What the judge's verdicts cost at list price, or None if none was asked."""
        return _priced(result.verdicts_usd for result in self.results)

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


def _kept(path: Path, kind: type[Record]) -> Iterator[Record]:
    """The records in a file the run writes as it goes, which isn't there until the first one."""
    return jsonl.read(path, kind) if path.exists() else iter(())


def _rate_of(results: Iterable[TrialResult]) -> Rate:
    scored = [result for result in results if result.scored]
    return Rate(sum(result.passed is True for result in scored), len(scored))


def _priced(costs: Iterable[float | None]) -> float | None:
    """The sum of the costs that are known, or None when none is."""
    known = [cost for cost in costs if cost is not None]
    return sum(known) if known else None


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
            results = list(_kept(path / "results.jsonl", TrialResult))
            failures = list(_kept(path / "errors.jsonl", TrialFailure))
        except UnreadableFileError as error:
            raise RunError(f"{str(path)!r} isn't a run Temper can read: {error}") from None
        except ValidationError as error:
            raise RunError(f"{str(path)!r} holds a manifest Temper can't read: {error}") from None
        except BadLineError as error:
            raise RunError(f"{str(path)!r} holds a record Temper can't read: {error}") from None
        return cls(path, manifest, results, failures)

    @property
    def answered(self) -> frozenset[Slot]:
        """The (case, trial) slots that already have an answer."""
        return frozenset((result.case_id, result.trial) for result in self._results)

    def add(self, result: TrialResult) -> None:
        """Keep an answered trial."""
        self._results.append(result)
        jsonl.append(self.path / "results.jsonl", result)

    def add_failure(self, failure: TrialFailure) -> None:
        """Keep a failed attempt."""
        self._failures.append(failure)
        jsonl.append(self.path / "errors.jsonl", failure)

    def record(self, request: Request, completion: Completion, latency_ms: float) -> None:
        """Keep a completion for replay, with how long it took, when the run spends money."""
        if self.manifest.charges:
            timed = completion.model_copy(update={"latency_ms": latency_ms})
            jsonl.append(self.path / "recording.jsonl", Recording.of(request, timed))

    def recorded(self) -> ReplayProvider:
        """Everything the run has recorded so far, to answer from before anything is bought twice.

        Raises:
            ProviderError: the recording can't be read.
        """
        path = self.path / "recording.jsonl"
        return ReplayProvider.from_file(path) if path.exists() else ReplayProvider([])

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
