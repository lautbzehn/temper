"""Running a suite: every case and trial side by side, each answer graded and kept as it lands.

The runner owns the retries, the time limit, and the budget, so a provider only
has to answer or say why it can't. A judge's verdict is asked for the way an
answer is, through the same limits. Whatever becomes of a request is written
down: an answer with its grades, a verdict with its cost, or a failure with its
reason. A failure is never scored as a wrong answer, and a verdict that never
came is never a failed check.
"""

from __future__ import annotations

import asyncio
import hashlib
import platform
import random
import secrets
import time
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from typing import TYPE_CHECKING, Literal

from temper import judge
from temper.checks import build_check
from temper.errors import ProviderError, RunError, TransientError
from temper.graders import Answer, Grader
from temper.loading import load_suite, swap_system_prompt
from temper.planning import Plan, Providers, answer_request, plan_run, providers_for
from temper.pricing import PRICED_ON, cost_usd
from temper.providers import served_matches
from temper.results import Manifest, Retry, RunFolder, RunOptions, TrialFailure, TrialResult
from temper.wording import dollars

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from temper.graders import Grade, JudgeCheck
    from temper.providers import Completion, Provider, ReplayProvider, Request
    from temper.results import FailureKind, Run
    from temper.suite import Case, Suite

BACKOFF_CAP_S = 30.0

# Where a completion came from: the run's own recording, the recording it replays, or a provider.
Source = Literal["own", "replay", "live"]


async def run_suite(
    suite: Suite,
    providers: Providers,
    *,
    out: Path,
    options: RunOptions | None = None,
) -> Run:
    """Run every case, several trials each, and keep the run under `out`.

    `options.trials` says how many; the suite's own count is the default. The
    run comes back whether or not every attempt produced an answer: the ones
    that didn't are in `run.failures`, and `resume_run` can try them again.

    Raises:
        SuiteError: the system prompt `options.system` names can't be read.
        ProviderError: the run couldn't start, so nothing was kept.
    """
    plan = await plan_run(suite, providers, options or RunOptions())
    return await complete_run(plan, start_run(plan, out=out))


async def resume_run(path: Path, providers: Providers | None = None) -> Run:
    """Pick up a kept run, answering only the (case, trial) slots that still have no answer.

    The suite is read from the file the run was started from. The providers
    are built from the run's options and closed afterwards, unless they are
    given, and then they're left open for their owner. Whatever the run
    already paid for is answered from its own recording, never bought again.

    Raises:
        RunError: the folder isn't a run, or its suite file has changed since.
        SuiteError: the suite file no longer loads.
        ProviderError: the run couldn't be picked up, so nothing more was kept.
    """
    suite, folder = reopen_run(path)
    options = folder.manifest.options
    if providers is not None:
        return await _resume(suite, providers, folder)
    async with aclosing(providers_for(suite, options)) as built:
        return await _resume(suite, built, folder)


async def _resume(suite: Suite, providers: Providers, folder: RunFolder) -> Run:
    plan = await plan_run(suite, providers, folder.manifest.options)
    folder.resume()
    return await complete_run(plan, folder)


def start_run(plan: Plan, *, out: Path) -> RunFolder:
    """Make a fresh run's folder under `out`, with the manifest of the run `plan` describes.

    It takes the plan, not a suite, so the folder can only ever describe the
    suite the run answers. `plan_run` comes first, so a run that can't start
    never leaves a folder behind.
    """
    return RunFolder.start(out, manifest_for(plan.suite, plan.providers, plan.options))


def reopen_run(path: Path) -> tuple[Suite, RunFolder]:
    """A kept run and its suite as its file says it, read back so the run can be picked up.

    The check that nothing has changed is made on the suite as the run
    answered it, its system prompt swapped in, and planning swaps it in
    again. Nothing is written: the folder's `resume` notes the resumption
    once the run is ready to go on.

    Raises:
        RunError: the folder isn't a run, the suite wasn't loaded from a file,
            or that file, or the system prompt the run used, has changed since.
        SuiteError: the suite file no longer loads, or the prompt can't be read.
    """
    folder = RunFolder.open(path)
    if folder.manifest.suite_path is None:
        raise RunError("this run's suite wasn't loaded from a file, so it can't be resumed")
    suite = load_suite(folder.manifest.suite_path)
    answered = swap_system_prompt(suite, folder.manifest.options.system)
    if fingerprint(answered) != folder.manifest.fingerprint:
        raise RunError(f"the suite has changed since run {folder.manifest.run_id} started")
    return suite, folder


async def complete_run(plan: Plan, folder: RunFolder) -> Run:
    """Answer every (case, trial) the folder still lacks, keeping each outcome as it lands.

    Raises:
        ProviderError: the run's own recording can't be read.
    """
    cases = {case.id: case for case in plan.suite.cases}
    answered = folder.answered
    todo = [slot for slot in folder.manifest.slots if slot not in answered]
    session = _Session(plan, folder)
    async with asyncio.TaskGroup() as group:
        for case_id, trial in todo:
            group.create_task(session.attempt(cases[case_id], trial))
    folder.finish(spent_usd=session.spent_usd)
    return folder.run()


def manifest_for(suite: Suite, providers: Providers, options: RunOptions) -> Manifest:
    """A manifest for a fresh run of `suite` on `providers`."""
    started = datetime.now(UTC)
    return Manifest(
        run_id=f"{started:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}",
        suite=suite.name,
        suite_path=suite.path.resolve() if suite.path else None,
        fingerprint=fingerprint(suite),
        provider="replay" if options.replay else suite.target.provider,
        model=suite.target.model,
        judge=suite.judge.model if suite.judged else None,
        cases_fingerprint=cases_fingerprint(suite),
        charges=providers.charges,
        case_ids=tuple(case.id for case in suite.cases),
        trials=options.trials or suite.trials,
        options=options,
        temper_version=version("temper-evals"),
        python_version=platform.python_version(),
        priced_on=PRICED_ON,
        started_at=started,
    )


def fingerprint(suite: Suite) -> str:
    """A short hash of everything the suite says, so a run is only resumed with its own suite."""
    return hashlib.sha256(suite.model_dump_json(by_alias=True).encode()).hexdigest()[:16]


def cases_fingerprint(suite: Suite) -> str:
    """A short hash of the cases alone, so two runs can be compared across a change of target."""
    cases = "\n".join(case.model_dump_json(exclude={"tags"}) for case in suite.cases)
    return hashlib.sha256(cases.encode()).hexdigest()[:16]


def backoff(attempt: int, retry_after: float | None, *, base: float) -> float:
    """How long to wait before the next try: the API's own ask, or a doubling delay with jitter."""
    if retry_after is not None:
        return min(retry_after, BACKOFF_CAP_S)
    ceiling = min(BACKOFF_CAP_S, base * 2 ** (attempt - 1))
    return random.uniform(0, ceiling)  # noqa: S311  (jitter spreads retries out; it isn't a secret)


class Budget:
    """What a run may spend. Each request reserves its worst case first, so nothing overshoots.

    A request cut off before it answered is counted at its worst case, since
    the API may well have billed it.
    """

    def __init__(self, limit_usd: float | None) -> None:
        self.limit_usd = limit_usd
        self.spent_usd = 0.0
        self._reserved_usd = 0.0

    def reserve(self, worst_case_usd: float) -> bool:
        """Set aside the most a request could cost, or say no when that would pass the limit."""
        committed = self.spent_usd + self._reserved_usd + worst_case_usd
        if self.limit_usd is not None and committed > self.limit_usd:
            return False
        self._reserved_usd += worst_case_usd
        return True

    def settle(self, worst_case_usd: float, actual_usd: float) -> None:
        """Swap a reservation for what the request really cost."""
        self._reserved_usd -= worst_case_usd
        self.spent_usd += actual_usd


@dataclass(frozen=True, slots=True)
class _Answered:
    """A request that got a completion: what came back, from where, how long it took, its cost."""

    completion: Completion
    source: Source
    latency_ms: float
    cost_usd: float | None
    attempts: int
    retries: tuple[Retry, ...]

    def result(self, request: Request, grades: Sequence[Grade]) -> TrialResult:
        return TrialResult(
            request=request,
            completion=self.completion,
            grades=tuple(grades),
            latency_ms=round(self.latency_ms, 1),
            cost_usd=self.cost_usd,
            attempts=self.attempts,
            retries=self.retries,
        )


@dataclass(frozen=True, slots=True)
class _Miss:
    """A request that got no completion: why, and what the attempts cost anyway."""

    kind: FailureKind
    reason: str
    cost_usd: float | None
    attempts: int
    retries: tuple[Retry, ...]

    def failure(self, request: Request) -> TrialFailure:
        return TrialFailure(
            case_id=request.case_id,
            trial=request.trial,
            kind=self.kind,
            reason=self.reason,
            attempts=self.attempts,
            retries=self.retries,
            cost_usd=self.cost_usd,
            at=datetime.now(UTC),
        )


@dataclass(slots=True)
class _Tries:
    """One request's attempts so far: how many were sent, and every retry."""

    request: Request
    sent: int = 0
    retries: list[Retry] = field(default_factory=list)

    def answered(
        self, completion: Completion, source: Source, latency_ms: float, cost: float | None
    ) -> _Answered:
        return _Answered(completion, source, latency_ms, cost, self.sent, tuple(self.retries))

    def miss(self, kind: FailureKind, reason: str, *, cost: float | None = None) -> _Miss:
        return _Miss(kind, reason, cost, self.sent, tuple(self.retries))


class _Session:
    """One run in progress: the shared limits, and what each attempt does.

    Before any request is sent, two recordings are looked in: the run's own,
    so a resumed run never buys again what it has, and the one it replays, if
    any. A completion found in either is free; one bought, or copied from a
    replay, is recorded, so the run's recording can always replay the run.
    """

    def __init__(self, plan: Plan, folder: RunFolder) -> None:
        self._plan = plan
        self._suite = plan.suite
        self._providers = plan.providers
        self._folder = folder
        self._options = folder.manifest.options
        self._own = folder.recorded()
        self._checks = {
            case.id: [build_check(check) for check in case.checks] for case in plan.suite.cases
        }
        self._budget = Budget(plan.budget_usd)
        self._limit = asyncio.Semaphore(self._options.concurrency)

    @property
    def spent_usd(self) -> float:
        """What the budget has counted as spent so far."""
        return self._budget.spent_usd

    async def attempt(self, case: Case, trial: int) -> None:
        """Answer one trial, grade it, asking the judge where a check needs it, and keep it."""
        request = answer_request(self._suite, case, trial)
        worst = self._plan.worst_answer_usd(case.id)
        outcome = await self._ask(request, self._providers.answers, worst)
        if isinstance(outcome, _Miss):
            self._folder.add_failure(outcome.failure(request))
            return
        self._keep(request, outcome)
        answer = Answer(
            text=outcome.completion.text,
            conversation=request.messages,
            latency_ms=outcome.latency_ms,
            cost_usd=outcome.cost_usd,
        )
        grades = [
            await self._grade(request, index, check, answer)
            for index, check in enumerate(self._checks[case.id])
        ]
        self._folder.add(outcome.result(request, grades))

    async def _grade(
        self, answered: Request, index: int, check: Grader | JudgeCheck, answer: Answer
    ) -> Grade:
        """A check's grade: decided here when it's code, asked of the judge when it isn't.

        A judge's completion is recorded only when it holds a verdict. One
        that doesn't is trouble with the judge, not a thing under test, and
        the judge is asked again next time rather than replayed.
        """
        if isinstance(check, Grader):
            return check.grade(answer)
        request = judge.verdict_request(self._suite, answered, index, check, answer)
        worst = self._plan.worst_verdict_usd(answered.case_id, index)
        outcome = await self._ask(request, self._providers.judge, worst)
        if isinstance(outcome, _Miss):
            return judge.no_verdict(check, outcome.reason, outcome.cost_usd)
        grade = judge.grade(check, outcome.completion, outcome.cost_usd)
        if grade.passed is not None:
            self._keep(request, outcome)
        return grade

    def _keep(self, request: Request, outcome: _Answered) -> None:
        """Record a completion the run bought or copied, so its recording can replay it."""
        if outcome.source != "own":
            self._folder.record(request, outcome.completion, outcome.latency_ms)

    async def _ask(
        self, request: Request, provider: Provider | None, worst: float
    ) -> _Answered | _Miss:
        """One request through every limit: a slot, the time limit, the budget, and the retries."""
        tries = _Tries(request)
        async with self._limit:
            try:
                async with asyncio.timeout(self._options.time_limit_s):
                    return await self._answer(tries, provider, worst)
            except TimeoutError:
                limit = self._options.time_limit_s
                return tries.miss("timeout", f"no answer within {limit:g} seconds")

    async def _answer(
        self, tries: _Tries, provider: Provider | None, worst: float
    ) -> _Answered | _Miss:
        """A recorded completion when one exists, or else the provider's, within the budget."""
        request = tries.request
        on_record = self._on_record(request)
        if on_record is not None:
            source, recording = on_record
            tries.sent += 1
            completion = await recording.complete(request)
            return self._check_model(tries, completion, source, completion.latency_ms or 0.0)
        if provider is None:
            return tries.miss(
                "provider", "nothing to answer from: the recording lacks this request"
            )
        return await self._buy(tries, provider, worst)

    def _on_record(self, request: Request) -> tuple[Source, ReplayProvider] | None:
        """Which recording already holds this very request, if either does."""
        if self._own.has(request):
            return "own", self._own
        replay = self._providers.recording
        if replay is not None and replay.has(request):
            return "replay", replay
        return None

    async def _buy(self, tries: _Tries, provider: Provider, worst: float) -> _Answered | _Miss:
        request = tries.request
        while True:
            if not self._budget.reserve(worst):
                reason = f"{dollars(worst)} more would pass the ${self._budget.limit_usd:g} budget"
                return tries.miss("budget", reason)
            tries.sent += 1
            started = time.perf_counter()
            try:
                completion = await provider.complete(request)
            except asyncio.CancelledError:
                self._budget.settle(worst, worst)
                raise
            except TransientError as error:
                self._budget.settle(worst, 0.0)
                if tries.sent >= self._options.attempts:
                    reason = f"gave up after {tries.sent} attempts; the last said: {error}"
                    return tries.miss("provider", reason)
                wait = backoff(tries.sent, error.retry_after, base=self._options.backoff_s)
                tries.retries.append(
                    Retry(attempt=tries.sent, reason=str(error), waited_s=round(wait, 3))
                )
                await asyncio.sleep(wait)
                continue
            except ProviderError as error:
                self._budget.settle(worst, 0.0)
                return tries.miss("provider", str(error))
            measured_ms = (time.perf_counter() - started) * 1000
            cost = cost_usd(completion.usage, completion.model)
            self._budget.settle(worst, (cost or 0.0) if provider.charges else 0.0)
            known_ms = completion.latency_ms
            return self._check_model(tries, completion, "live", known_ms or measured_ms)

    def _check_model(
        self, tries: _Tries, completion: Completion, source: Source, latency_ms: float
    ) -> _Answered | _Miss:
        """The completion as answered, unless a model other than the one asked for gave it."""
        request = tries.request
        cost = cost_usd(completion.usage, completion.model)
        if not served_matches(request.model, completion.model):
            reason = f"asked for {request.model!r}, but {completion.model!r} answered"
            return tries.miss("served-model", reason, cost=cost)
        return tries.answered(completion, source, latency_ms, cost)
