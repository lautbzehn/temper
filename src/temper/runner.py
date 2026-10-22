"""Running a suite: every case and trial side by side, graded as each answer lands."""

from __future__ import annotations

import asyncio
import hashlib
import platform
import secrets
import time
from datetime import UTC, datetime
from importlib.metadata import version
from typing import TYPE_CHECKING

from temper.graders import build_grader
from temper.providers import Request
from temper.results import Manifest, Run, TrialResult

if TYPE_CHECKING:
    from temper.providers import Provider
    from temper.suite import Case, Suite


async def run_suite(
    suite: Suite,
    provider: Provider,
    *,
    trials: int | None = None,
    concurrency: int = 8,
) -> Run:
    """Ask every case `trials` times, falling back to the suite's own count, and grade each answer.

    At most `concurrency` trials wait on the provider at once. Results come
    back in suite order, case by case and trial by trial, whatever order they
    finish in.

    Raises:
        ValueError: `trials` or `concurrency` is less than 1.
        ExceptionGroup: a provider couldn't answer. The run stops, and the group
            holds each `ProviderError` that stopped it.
    """
    count = trials if trials is not None else suite.trials
    if count < 1 or concurrency < 1:
        raise ValueError("trials and concurrency must each be at least 1")
    limit = asyncio.Semaphore(concurrency)
    graders = {case.id: [build_grader(check) for check in case.checks] for case in suite.cases}

    async def attempt(case: Case, trial: int) -> TrialResult:
        request = Request(
            case_id=case.id,
            trial=trial,
            model=suite.target.model,
            system=suite.target.system,
            messages=case.conversation,
            max_tokens=suite.target.max_tokens,
        )
        async with limit:
            started = time.perf_counter()
            completion = await provider.complete(request)
            elapsed = time.perf_counter() - started
        return TrialResult(
            case_id=case.id,
            trial=trial,
            answer=completion.text,
            model=completion.model,
            latency_ms=round(elapsed * 1000, 1),
            grades=tuple(grader.grade(completion.text) for grader in graders[case.id]),
        )

    started_at = datetime.now(UTC)
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(attempt(case, trial))
            for case in suite.cases
            for trial in range(1, count + 1)
        ]
    results = tuple(task.result() for task in tasks)
    return Run(manifest=_manifest(suite, count, started_at), results=results)


def _manifest(suite: Suite, trials: int, started_at: datetime) -> Manifest:
    return Manifest(
        run_id=f"{started_at:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}",
        suite=suite.name,
        fingerprint=_fingerprint(suite),
        provider=suite.target.provider,
        model=suite.target.model,
        cases=len(suite.cases),
        trials=trials,
        temper_version=version("temper-evals"),
        python_version=platform.python_version(),
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )


def _fingerprint(suite: Suite) -> str:
    """A short hash of everything the suite says, so runs of different suites never get compared."""
    return hashlib.sha256(suite.model_dump_json(by_alias=True).encode()).hexdigest()[:16]
