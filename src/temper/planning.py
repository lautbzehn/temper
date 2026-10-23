"""Planning a run before anything is kept: who answers, what each request can cost, and the budget.

Every request that will cost money is counted first, with free calls that
also prove each provider's credentials and model. The counts set the worst
case a budget reserves for each request, and are what a dry run prints.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from temper import judge
from temper.checks import judge_checks
from temper.errors import ProviderError
from temper.graders import Answer
from temper.loading import swap_system_prompt
from temper.pricing import cost_usd, price_of
from temper.providers import (
    ReplayProvider,
    Request,
    Usage,
    build_judge,
    build_provider,
    same_model,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from temper.providers import Provider
    from temper.results import RunOptions
    from temper.suite import Case, Suite


@dataclass(frozen=True, slots=True)
class Providers:
    """Where a run's answers and verdicts come from, and the recording it replays, if any.

    A run that replays takes its answers from `recording` and nowhere else,
    and its verdicts from there when it holds them and from `judge` when it
    doesn't, so a revised judge can be tried on the very same answers.
    """

    answers: Provider
    judge: Provider | None = None
    recording: ReplayProvider | None = None

    @property
    def charges(self) -> bool:
        """Whether anything the run asks for costs money."""
        return self.answers.charges or (self.judge is not None and self.judge.charges)

    async def aclose(self) -> None:
        """Let go of whatever the providers hold open."""
        await self.answers.aclose()
        if self.judge is not None:
            await self.judge.aclose()


def providers_for(suite: Suite, options: RunOptions) -> Providers:
    """What a run answers from: the recording `options.replay` names, or the suite's own target.

    The suite's judge is set up too, whenever a check needs one.

    Raises:
        ProviderError: the recording, the target's provider, or the judge couldn't be set up.
    """
    recording = ReplayProvider.from_file(options.replay) if options.replay is not None else None
    answers = recording if recording is not None else build_provider(suite.target, suite.folder)
    decides = build_judge(suite.judge) if suite.judged else None
    return Providers(answers, decides, recording)


@dataclass(frozen=True, slots=True)
class Estimates:
    """Input tokens counted ahead of a run, and how many verdicts the recording already holds.

    A verdict's prompt is counted before the answer is in it, since the answer
    isn't known yet, so an answer's own ceiling is added when a worst case is
    priced. When a run replays, the recorded answer is in the prompt, and a
    verdict the recording holds isn't counted at all.
    """

    answers: Mapping[str, int] = field(default_factory=dict)
    verdicts: Mapping[tuple[str, int], int] = field(default_factory=dict)
    verdicts_on_record: int = 0


@dataclass(frozen=True, slots=True)
class Plan:
    """A run as planned: the suite it answers, who answers, its options, and what it may cost.

    `suite` is the suite as the run answers it, with any system prompt the
    options swap in already in place, so whatever starts a run from a plan
    answers, and describes, the right one.
    """

    suite: Suite
    providers: Providers
    options: RunOptions
    estimates: Estimates
    budget_usd: float | None

    def worst_answer_usd(self, case_id: str) -> float:
        """The most one answer can cost: its input, plus `max_tokens` of output, at list price."""
        if not self.providers.answers.charges:
            return 0.0
        target = self.suite.target
        return ceiling(target.model, self.estimates.answers.get(case_id, 0), target.max_tokens)

    def worst_verdict_usd(self, case_id: str, check: int) -> float:
        """The most one verdict can cost: the prompt at its longest, plus the judge's output.

        Nothing, when the verdict was never counted: the judge is free, or
        the recording holds every trial's verdict on this check.
        """
        judge = self.providers.judge
        counted = self.estimates.verdicts.get((case_id, check))
        if judge is None or not judge.charges or counted is None:
            return 0.0
        prompt = counted + self.suite.target.max_tokens
        return ceiling(self.suite.judge.model, prompt, self.suite.judge.max_tokens)

    def worst_trial_usd(self, case: Case) -> float:
        """The most one trial of `case` can cost: its answer, then each of its verdicts."""
        verdicts = sum(self.worst_verdict_usd(case.id, check) for check in case.judged)
        return self.worst_answer_usd(case.id) + verdicts


async def plan_run(suite: Suite, providers: Providers, options: RunOptions) -> Plan:
    """Make sure a run can start, before anything is kept.

    Every request that will cost money is counted: free calls that prove each
    provider's credentials and model, and set the worst case the budget holds
    for a request. A budget needs models with a list price to reserve against.
    A run that spends nothing has nothing to count or budget.

    Raises:
        SuiteError: the system prompt the options name can't be read.
        ProviderError: the suite has judge checks but no judge, or judges a
            model with itself; a provider couldn't count tokens; or a budget
            was asked for on a model with no list price.
    """
    suite = swap_system_prompt(suite, options.system)
    if suite.judged:
        if providers.judge is None:
            raise ProviderError("the suite has judge checks, but no judge was given to decide them")
        under_test = suite.target.model
        if under_test is not None and same_model(suite.judge.model, under_test):
            raise ProviderError(f"the judge can't be the model under test, {under_test!r}")
    if not providers.charges:
        return Plan(suite, providers, options, Estimates(), None)
    if options.budget_usd is not None:
        for model in charged_models(suite, providers):
            if model is None or price_of(model) is None:
                raise ProviderError(
                    f"can't hold a budget for model {model!r}: it has no list price, "
                    "so nothing can be reserved"
                )
    return replace(await _estimate(suite, providers, options), budget_usd=options.budget_usd)


def charged_models(suite: Suite, providers: Providers) -> list[str | None]:
    """The models a run will pay for, and so must be able to price."""
    models: list[str | None] = []
    if providers.answers.charges:
        models.append(suite.target.model)
    if suite.judged and providers.judge is not None and providers.judge.charges:
        models.append(suite.judge.model)
    return models


async def estimate_suite(suite: Suite, providers: Providers, options: RunOptions) -> Plan:
    """Count every request's input tokens: a plan with no budget held, which a dry run prints.

    Raises:
        SuiteError: the system prompt the options name can't be read.
        ProviderError: a provider couldn't count a request's tokens.
    """
    return await _estimate(swap_system_prompt(suite, options.system), providers, options)


async def _estimate(suite: Suite, providers: Providers, options: RunOptions) -> Plan:
    trials = options.trials or suite.trials
    limit = asyncio.Semaphore(options.concurrency)
    counted: dict[tuple[str, int | None], int] = {}
    trouble: list[ProviderError] = []

    # Trouble is kept as a value so the task group never wraps it in a group.
    async def count(request: Request, provider: Provider) -> None:
        async with limit:
            try:
                tokens = await provider.estimate(request)
            except ProviderError as error:
                trouble.append(error)
                return
        key = (request.case_id, request.check)
        counted[key] = max(counted.get(key, 0), tokens)

    on_record = 0
    async with asyncio.TaskGroup() as group:
        for case in suite.cases:
            group.create_task(count(answer_request(suite, case, 1), providers.answers))
            if providers.judge is None:
                continue
            for request, recorded in _verdicts(suite, providers.recording, case, trials):
                if recorded:
                    on_record += 1
                else:
                    group.create_task(count(request, providers.judge))
    if trouble:
        raise trouble[0]
    estimates = Estimates(
        answers={case_id: n for (case_id, check), n in counted.items() if check is None},
        verdicts={(c, check): n for (c, check), n in counted.items() if check is not None},
        verdicts_on_record=on_record,
    )
    return Plan(suite, providers, options, estimates, None)


def _verdicts(
    suite: Suite, recording: ReplayProvider | None, case: Case, trials: int
) -> Iterator[tuple[Request, bool]]:
    """Each verdict request a run of `case` would make, and whether the recording holds it.

    With no recording, one request per judge check with a blank answer in
    it, since the answer isn't known yet. With one, a request per judge check
    and trial whose answer is on record, with that answer in it; an answer
    that isn't on record will be refused, so nothing is asked about it.
    """
    judged = judge_checks(case)
    if recording is None:
        asked = answer_request(suite, case, 1)
        blank = Answer(text="", conversation=case.conversation, latency_ms=0.0)
        for index, check in judged:
            yield judge.verdict_request(suite, asked, index, check, blank), False
        return
    for trial in range(1, trials + 1):
        asked = answer_request(suite, case, trial)
        completion = recording.recorded(asked)
        if completion is None:
            continue
        answer = Answer(
            text=completion.text,
            conversation=case.conversation,
            latency_ms=completion.latency_ms or 0.0,
        )
        for index, check in judged:
            request = judge.verdict_request(suite, asked, index, check, answer)
            yield request, recording.has(request)


def answer_request(suite: Suite, case: Case, trial: int) -> Request:
    """What the model under test is asked for one trial of a case."""
    return Request(
        case_id=case.id,
        trial=trial,
        model=suite.target.model,
        system=suite.target.system,
        messages=case.conversation,
        max_tokens=suite.target.max_tokens,
        options=dict(suite.target.options),
    )


def ceiling(model: str | None, input_tokens: int, max_tokens: int) -> float:
    """What `input_tokens` in and `max_tokens` out cost on `model` at list price, or nothing."""
    if model is None:
        return 0.0
    return cost_usd(Usage(input_tokens=input_tokens, output_tokens=max_tokens), model) or 0.0
