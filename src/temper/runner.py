"""Running a suite: every case and trial side by side, each answer graded and kept as it lands.

The runner owns the retries, the time limit, and the budget, so a provider only
has to answer or say why it can't. Whatever becomes of an attempt is written
down: an answer with its grades, or a failure with its reason. A failure is
never scored as a wrong answer.
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
from typing import TYPE_CHECKING

from temper.errors import ProviderError, RunError, TransientError
from temper.graders import build_grader
from temper.loading import load_suite
from temper.pricing import PRICED_ON, cost_usd, price_of
from temper.providers import ReplayProvider, Request, Usage, build_provider
from temper.results import Manifest, Retry, RunFolder, RunOptions, TrialFailure, TrialResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from temper.graders import Grader
    from temper.providers import Completion, Provider
    from temper.results import FailureKind, Run
    from temper.suite import Case, Suite

BACKOFF_CAP_S = 30.0


@dataclass(frozen=True, slots=True)
class Plan:
    """What a run knows before it starts: each case's input tokens, and the budget it will hold."""

    estimates: Mapping[str, int]
    budget_usd: float | None


async def run_suite(
    suite: Suite,
    provider: Provider,
    *,
    out: Path,
    options: RunOptions | None = None,
) -> Run:
    """Run every case, several trials each, and keep the run under `out`.

    `options.trials` says how many; the suite's own count is the default. The
    run comes back whether or not every attempt produced an answer: the ones
    that didn't are in `run.failures`, and `resume_run` can try them again.

    Raises:
        ProviderError: the run couldn't start, so nothing was kept.
    """
    options = options or RunOptions()
    plan = await plan_run(suite, provider, options)
    folder = start_run(suite, provider, out=out, options=options)
    return await complete_run(suite, provider, folder, plan)


async def resume_run(path: Path, provider: Provider | None = None) -> Run:
    """Pick up a kept run, answering only the (case, trial) slots that still have no answer.

    The suite is read from the file the run was started from. The provider is
    built from the run's options and closed afterwards, unless one is given,
    which is then left open for its owner.

    Raises:
        RunError: the folder isn't a run, or its suite file has changed since.
        SuiteError: the suite file no longer loads.
        ProviderError: the run couldn't be picked up, so nothing more was kept.
    """
    suite, folder = reopen_run(path)
    options = folder.manifest.options
    if provider is not None:
        return await _resume(suite, provider, folder)
    async with aclosing(provider_for(suite, options)) as built:
        return await _resume(suite, built, folder)


async def _resume(suite: Suite, provider: Provider, folder: RunFolder) -> Run:
    plan = await plan_run(suite, provider, folder.manifest.options)
    folder.resume()
    return await complete_run(suite, provider, folder, plan)


async def plan_run(suite: Suite, provider: Provider, options: RunOptions) -> Plan:
    """Make sure a run can start, before anything is kept.

    A provider that charges is asked to count one case's tokens: a free call
    that proves the credentials and the model. A budget needs every case's
    count, and a model with a list price to reserve against. A provider that
    answers for free has nothing to budget, so no budget is held.

    Raises:
        ProviderError: the provider couldn't count tokens, or a budget was
            asked for on a model with no list price.
    """
    if not provider.charges:
        return Plan({}, None)
    if options.budget_usd is None:
        await provider.estimate(_request(suite, suite.cases[0], 1))
        return Plan({}, None)
    model = suite.target.model
    if model is None or price_of(model) is None:
        raise ProviderError(
            f"can't hold a budget for model {model!r}: it has no list price, "
            "so nothing can be reserved"
        )
    return Plan(await estimate_suite(suite, provider, options), options.budget_usd)


def start_run(
    suite: Suite,
    provider: Provider,
    *,
    out: Path,
    options: RunOptions | None = None,
) -> RunFolder:
    """Make a fresh run's folder under `out`, with its manifest.

    `plan_run` comes first, so a run that can't start never leaves a folder behind.
    """
    return RunFolder.start(out, manifest_for(suite, provider, options or RunOptions()))


def reopen_run(path: Path) -> tuple[Suite, RunFolder]:
    """A kept run and its suite, read back so the run can be picked up.

    Nothing is written: the folder's `resume` notes the resumption once the
    run is ready to go on.

    Raises:
        RunError: the folder isn't a run, the suite wasn't loaded from a file,
            or that file has changed since the run started.
        SuiteError: the suite file no longer loads.
    """
    folder = RunFolder.open(path)
    if folder.manifest.suite_path is None:
        raise RunError("this run's suite wasn't loaded from a file, so it can't be resumed")
    suite = load_suite(folder.manifest.suite_path)
    if fingerprint(suite) != folder.manifest.fingerprint:
        raise RunError(f"the suite has changed since run {folder.manifest.run_id} started")
    return suite, folder


async def complete_run(suite: Suite, provider: Provider, folder: RunFolder, plan: Plan) -> Run:
    """Answer every (case, trial) the folder still lacks, keeping each outcome as it lands."""
    cases = {case.id: case for case in suite.cases}
    answered = folder.answered
    todo = [slot for slot in folder.manifest.slots if slot not in answered]
    session = _Session(suite, provider, folder, plan)
    async with asyncio.TaskGroup() as group:
        for case_id, trial in todo:
            group.create_task(session.attempt(cases[case_id], trial))
    folder.finish(spent_usd=session.spent_usd)
    return folder.run()


def provider_for(suite: Suite, options: RunOptions) -> Provider:
    """What a run answers from: the recording `options.replay` names, or the suite's own target.

    Raises:
        ProviderError: the recording or the target's provider couldn't be set up.
    """
    if options.replay is not None:
        return ReplayProvider.from_file(options.replay)
    return build_provider(suite.target, suite.folder)


async def estimate_suite(suite: Suite, provider: Provider, options: RunOptions) -> dict[str, int]:
    """How many input tokens each case takes, by case id.

    Raises:
        ProviderError: the provider couldn't count a case's tokens.
    """
    limit = asyncio.Semaphore(options.concurrency)

    # An error comes back as a value so the task group never wraps it in a group.
    async def estimate(case: Case) -> tuple[str, int | ProviderError]:
        async with limit:
            try:
                return case.id, await provider.estimate(_request(suite, case, 1))
            except ProviderError as error:
                return case.id, error

    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(estimate(case)) for case in suite.cases]
    estimates: dict[str, int] = {}
    for case_id, outcome in (task.result() for task in tasks):
        if isinstance(outcome, ProviderError):
            raise outcome
        estimates[case_id] = outcome
    return estimates


def worst_case_usd(suite: Suite, input_tokens: int) -> float:
    """The most one trial can cost: its input, plus `max_tokens` of output, at list price."""
    usage = Usage(input_tokens=input_tokens, output_tokens=suite.target.max_tokens)
    return (cost_usd(usage, suite.target.model) if suite.target.model else None) or 0.0


def manifest_for(suite: Suite, provider: Provider, options: RunOptions) -> Manifest:
    """A manifest for a fresh run of `suite` on `provider`."""
    started = datetime.now(UTC)
    return Manifest(
        run_id=f"{started:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}",
        suite=suite.name,
        suite_path=suite.path.resolve() if suite.path else None,
        fingerprint=fingerprint(suite),
        provider="replay" if options.replay else suite.target.provider,
        model=suite.target.model,
        charges=provider.charges,
        case_ids=tuple(case.id for case in suite.cases),
        trials=options.trials or suite.trials,
        options=options,
        temper_version=version("temper-evals"),
        python_version=platform.python_version(),
        priced_on=PRICED_ON,
        started_at=started,
    )


def fingerprint(suite: Suite) -> str:
    """A short hash of everything the suite says, so runs of different suites never get compared."""
    return hashlib.sha256(suite.model_dump_json(by_alias=True).encode()).hexdigest()[:16]


def backoff(attempt: int, retry_after: float | None, *, base: float) -> float:
    """How long to wait before the next try: the API's own ask, or a doubling delay with jitter."""
    if retry_after is not None:
        return min(retry_after, BACKOFF_CAP_S)
    ceiling = min(BACKOFF_CAP_S, base * 2 ** (attempt - 1))
    return random.uniform(0, ceiling)  # noqa: S311  (jitter spreads retries out; it isn't a secret)


def served_matches(requested: str | None, served: str) -> bool:
    """Whether the model that answered is the one asked for, allowing a dated snapshot of it."""
    return requested is None or served == requested or served.startswith(f"{requested}-")


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


def _request(suite: Suite, case: Case, trial: int) -> Request:
    return Request(
        case_id=case.id,
        trial=trial,
        model=suite.target.model,
        system=suite.target.system,
        messages=case.conversation,
        max_tokens=suite.target.max_tokens,
        options=dict(suite.target.options),
    )


@dataclass(slots=True)
class _Tries:
    """One trial's attempts so far: how many requests were sent, and every retry."""

    request: Request
    sent: int = 0
    retries: list[Retry] = field(default_factory=list)

    def failure(self, kind: FailureKind, reason: str, *, cost: float | None = None) -> TrialFailure:
        return TrialFailure(
            case_id=self.request.case_id,
            trial=self.request.trial,
            kind=kind,
            reason=reason,
            attempts=self.sent,
            retries=tuple(self.retries),
            cost_usd=cost,
            at=datetime.now(UTC),
        )

    def result(
        self,
        completion: Completion,
        graders: Sequence[Grader],
        latency_ms: float,
        cost: float | None,
    ) -> TrialResult:
        return TrialResult(
            request=self.request,
            completion=completion,
            grades=tuple(grader.grade(completion.text) for grader in graders),
            latency_ms=round(latency_ms, 1),
            cost_usd=cost,
            attempts=self.sent,
            retries=tuple(self.retries),
        )


class _Session:
    """One run in progress: the shared limits, and what each attempt does."""

    def __init__(self, suite: Suite, provider: Provider, folder: RunFolder, plan: Plan) -> None:
        self._suite = suite
        self._provider = provider
        self._folder = folder
        self._options = folder.manifest.options
        self._graders = {
            case.id: [build_grader(check) for check in case.checks] for case in suite.cases
        }
        self._worst = {
            case_id: worst_case_usd(suite, tokens) for case_id, tokens in plan.estimates.items()
        }
        self._budget = Budget(plan.budget_usd)
        self._limit = asyncio.Semaphore(self._options.concurrency)

    @property
    def spent_usd(self) -> float:
        """What the budget has counted as spent so far."""
        return self._budget.spent_usd

    async def attempt(self, case: Case, trial: int) -> None:
        """Answer one trial, retrying when the provider says to, and keep what became of it."""
        tries = _Tries(_request(self._suite, case, trial))
        async with self._limit:
            try:
                async with asyncio.timeout(self._options.time_limit_s):
                    outcome = await self._answer(tries, self._graders[case.id])
            except TimeoutError:
                reason = f"no answer within {self._options.time_limit_s:g} seconds"
                outcome = tries.failure("timeout", reason)
        if isinstance(outcome, TrialResult):
            self._folder.add(outcome)
        else:
            self._folder.add_failure(outcome)

    async def _answer(self, tries: _Tries, graders: Sequence[Grader]) -> TrialResult | TrialFailure:
        request = tries.request
        worst = self._worst.get(request.case_id, 0.0)
        while True:
            if not self._budget.reserve(worst):
                reason = f"${worst:.4f} more would pass the ${self._budget.limit_usd:g} budget"
                return tries.failure("budget", reason)
            tries.sent += 1
            started = time.perf_counter()
            try:
                completion = await self._provider.complete(request)
            except asyncio.CancelledError:
                self._budget.settle(worst, worst)
                raise
            except TransientError as error:
                self._budget.settle(worst, 0.0)
                if tries.sent >= self._options.attempts:
                    reason = f"gave up after {tries.sent} attempts; the last said: {error}"
                    return tries.failure("provider", reason)
                wait = backoff(tries.sent, error.retry_after, base=self._options.backoff_s)
                tries.retries.append(
                    Retry(attempt=tries.sent, reason=str(error), waited_s=round(wait, 3))
                )
                await asyncio.sleep(wait)
                continue
            except ProviderError as error:
                self._budget.settle(worst, 0.0)
                return tries.failure("provider", str(error))
            latency_ms = (time.perf_counter() - started) * 1000
            cost = cost_usd(completion.usage, completion.model)
            self._budget.settle(worst, cost or 0.0 if self._provider.charges else 0.0)
            if not served_matches(request.model, completion.model):
                reason = f"asked for {request.model!r}, but {completion.model!r} answered"
                return tries.failure("served-model", reason, cost=cost)
            return tries.result(completion, graders, latency_ms, cost)
