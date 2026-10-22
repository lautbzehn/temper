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
from datetime import UTC, datetime
from importlib.metadata import version
from itertools import count
from typing import TYPE_CHECKING

from temper.errors import ProviderError, RunError, TransientError
from temper.graders import build_grader
from temper.loading import load_suite
from temper.pricing import PRICED_ON, cost_usd
from temper.providers import ReplayProvider, Request, Usage, build_provider
from temper.results import Manifest, Retry, RunFolder, RunOptions, TrialFailure, TrialResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from temper.graders import Grader
    from temper.providers import Provider
    from temper.results import FailureKind, Run
    from temper.suite import Case, Suite

BACKOFF_CAP_S = 30.0


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
    that didn't are in `run.failures`, and `open_run` can pick them up again.

    Raises:
        ProviderError: the provider couldn't estimate a case, which a budget needs.
    """
    folder = start_run(suite, provider, out=out, options=options)
    return await run_folder(suite, provider, folder)


def start_run(
    suite: Suite,
    provider: Provider,
    *,
    out: Path,
    options: RunOptions | None = None,
) -> RunFolder:
    """Make a fresh run's folder under `out`, with its manifest, before anything is asked."""
    return RunFolder.start(out, manifest_for(suite, provider, options or RunOptions()))


def open_run(path: Path) -> tuple[Suite, RunFolder]:
    """A kept run and its suite, reopened to pick up where the run stopped.

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
    folder.resume()
    return suite, folder


async def run_folder(suite: Suite, provider: Provider, folder: RunFolder) -> Run:
    """Answer every (case, trial) the folder still lacks, keeping each outcome as it lands.

    A provider that charges is first asked to count one case's tokens: a free
    call that proves the credentials and the model before any money is spent.

    Raises:
        ProviderError: the preflight failed, or a budget needs estimates the
            provider couldn't give.
    """
    options = folder.manifest.options
    cases = {case.id: case for case in suite.cases}
    todo = [slot for slot in folder.manifest.slots if slot not in folder.answered]
    if provider.charges and todo:
        await provider.estimate(_request(suite, cases[todo[0][0]], 1))
    estimates = await estimate_suite(suite, provider, options) if options.budget_usd else {}
    session = _Session(suite, provider, folder, estimates)
    async with asyncio.TaskGroup() as group:
        for case_id, trial in todo:
            group.create_task(session.attempt(cases[case_id], trial))
    folder.finish()
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
    """What a run may spend. Each request reserves its worst case first, so nothing overshoots."""

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
    )


class _Session:
    """One run in progress: the shared limits, and what each attempt does."""

    def __init__(
        self,
        suite: Suite,
        provider: Provider,
        folder: RunFolder,
        estimates: Mapping[str, int],
    ) -> None:
        self._suite = suite
        self._provider = provider
        self._folder = folder
        self._options = folder.manifest.options
        self._graders = {
            case.id: [build_grader(check) for check in case.checks] for case in suite.cases
        }
        self._worst = {
            case_id: worst_case_usd(suite, tokens) for case_id, tokens in estimates.items()
        }
        self._budget = Budget(self._options.budget_usd)
        self._limit = asyncio.Semaphore(self._options.concurrency)

    async def attempt(self, case: Case, trial: int) -> None:
        """Answer one trial, retrying when the provider says to, and keep what became of it."""
        request = _request(self._suite, case, trial)
        retries: list[Retry] = []
        async with self._limit:
            try:
                async with asyncio.timeout(self._options.time_limit_s):
                    outcome = await self._answer(request, retries, self._graders[case.id])
            except TimeoutError:
                reason = f"no answer within {self._options.time_limit_s:g} seconds"
                outcome = self._failure(request, "timeout", reason, len(retries) + 1)
        if isinstance(outcome, TrialResult):
            self._folder.add(outcome)
        else:
            self._folder.add_failure(outcome)

    async def _answer(
        self, request: Request, retries: list[Retry], graders: Sequence[Grader]
    ) -> TrialResult | TrialFailure:
        worst = self._worst.get(request.case_id, 0.0)
        for attempt in count(1):
            if not self._budget.reserve(worst):
                reason = f"${worst:.4f} more would pass the ${self._options.budget_usd:g} budget"
                return self._failure(request, "budget", reason, attempt)
            started = time.perf_counter()
            try:
                completion = await self._provider.complete(request)
            except TransientError as error:
                self._budget.settle(worst, 0.0)
                if attempt >= self._options.attempts:
                    reason = f"gave up after {attempt} attempts; the last said: {error}"
                    return self._failure(request, "provider", reason, attempt)
                wait = backoff(attempt, error.retry_after, base=self._options.backoff_s)
                retries.append(Retry(attempt=attempt, reason=str(error), waited_s=round(wait, 3)))
                await asyncio.sleep(wait)
                continue
            except ProviderError as error:
                self._budget.settle(worst, 0.0)
                return self._failure(request, "provider", str(error), attempt)
            latency_ms = (time.perf_counter() - started) * 1000
            cost = cost_usd(completion.usage, completion.model)
            self._budget.settle(worst, cost or 0.0)
            if not served_matches(request.model, completion.model):
                reason = f"asked for {request.model!r}, but {completion.model!r} answered"
                return self._failure(request, "served-model", reason, attempt)
            return TrialResult(
                request=request,
                completion=completion,
                grades=tuple(grader.grade(completion.text) for grader in graders),
                latency_ms=round(latency_ms, 1),
                cost_usd=cost,
                attempts=attempt,
                retries=tuple(retries),
            )
        raise AssertionError("unreachable: every path above returns")

    @staticmethod
    def _failure(request: Request, kind: FailureKind, reason: str, attempts: int) -> TrialFailure:
        return TrialFailure(
            case_id=request.case_id,
            trial=request.trial,
            kind=kind,
            reason=reason,
            attempts=attempts,
            at=datetime.now(UTC),
        )
