from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from hypothesis import given
from hypothesis import strategies as st

from temper.errors import ProviderError, RunError, TransientError
from temper.loading import load_suite
from temper.planning import Providers
from temper.pricing import cost_usd
from temper.providers import (
    Completion,
    FakeProvider,
    ReplayProvider,
    Request,
    Usage,
    served_matches,
)
from temper.results import RunFolder, RunOptions
from temper.runner import (
    BACKOFF_CAP_S,
    Budget,
    backoff,
    complete_run,
    reopen_run,
    resume_run,
    start_run,
)
from tests.support import Scripted, Slow, Stuck, answer, case, make_suite, plan, run

if TYPE_CHECKING:
    from pathlib import Path

    from tests.support import Files

QUICK = RunOptions(backoff_s=0.001)


def test_results_come_back_in_suite_order_whatever_order_they_finish(tmp_path: Path) -> None:
    provider = Slow()
    suite = make_suite(case("first"), case("second"), trials=2)

    finished = run(suite, provider, tmp_path)

    in_suite_order = [("first", 1), ("first", 2), ("second", 1), ("second", 2)]
    assert provider.seen == in_suite_order[::-1]
    assert [(r.case_id, r.trial) for r in finished.results] == in_suite_order


def test_no_more_than_the_concurrency_limit_wait_at_once(tmp_path: Path) -> None:
    provider = Slow()
    suite = make_suite(*(case(f"case-{n}") for n in range(6)), trials=2)

    run(suite, provider, tmp_path, RunOptions(concurrency=3))

    assert provider.most_in_flight == 3


def test_each_answer_is_graded_by_every_check(tmp_path: Path) -> None:
    suite = make_suite(
        case(
            "complaint",
            {"type": "contains", "text": "sorry"},
            {"type": "not_contains", "text": "calm down"},
        )
    )
    provider = FakeProvider({"complaint": ["Sorry! Please calm down."]})

    [result] = run(suite, provider, tmp_path).results

    assert [grade.passed for grade in result.grades] == [True, False]
    assert not result.passed
    assert result.answer.text == "Sorry! Please calm down."
    assert result.completion.model == "fake-1"


def test_trials_default_to_the_suite_and_can_be_overridden(tmp_path: Path) -> None:
    suite = make_suite(case("only"), trials=3)
    provider = FakeProvider({"only": ["yes"]})

    assert len(run(suite, provider, tmp_path).results) == 3
    assert len(run(suite, provider, tmp_path, RunOptions(trials=5)).results) == 5


def test_the_manifest_records_what_ran(tmp_path: Path) -> None:
    suite = make_suite(case("a"), case("b"), trials=2, name="paper-sales")

    manifest = run(suite, FakeProvider({"a": ["yes"], "b": ["no"]}), tmp_path).manifest

    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", manifest.run_id)
    assert (manifest.suite, manifest.provider, manifest.model) == ("paper-sales", "fake", "fake-1")
    assert (manifest.case_ids, manifest.trials) == (("a", "b"), 2)
    assert manifest.finished_at is not None
    assert manifest.started_at <= manifest.finished_at
    assert manifest.suite_path is None


def test_the_fingerprint_changes_with_the_suite_and_only_then(tmp_path: Path) -> None:
    def fingerprint(*texts: str) -> str:
        suite = make_suite(*(case(text) for text in texts))
        provider = FakeProvider({text: ["yes"] for text in texts})
        return run(suite, provider, tmp_path).manifest.fingerprint

    assert fingerprint("a") == fingerprint("a")
    assert fingerprint("a") != fingerprint("b")


def test_a_passing_problem_is_retried_and_the_retries_are_written_down(tmp_path: Path) -> None:
    suite = make_suite(case("flaky"))
    provider = Scripted({"flaky": [TransientError("busy"), TransientError("busy"), answer()]})

    [result] = run(suite, provider, tmp_path, QUICK).results

    assert result.attempts == 3
    assert [retry.attempt for retry in result.retries] == [1, 2]
    assert all(retry.reason == "busy" for retry in result.retries)
    assert provider.calls == [("flaky", 1)] * 3


def test_the_runner_gives_up_after_the_allowed_attempts(tmp_path: Path) -> None:
    suite = make_suite(case("down"))
    provider = Scripted({"down": [TransientError("busy")] * 2})

    finished = run(suite, provider, tmp_path, RunOptions(attempts=2, backoff_s=0.001))

    assert finished.results == ()
    [failure] = finished.failures
    assert (failure.kind, failure.attempts) == ("provider", 2)
    assert failure.reason == "gave up after 2 attempts; the last said: busy"
    assert [retry.attempt for retry in failure.retries] == [1]


def test_a_failure_in_one_case_never_touches_the_others(tmp_path: Path) -> None:
    suite = make_suite(case("fine"), case("broken"))
    provider = Scripted({"fine": [answer()], "broken": [ProviderError("no such model")]})

    finished = run(suite, provider, tmp_path)

    assert [r.case_id for r in finished.results] == ["fine"]
    assert [(f.case_id, f.kind, f.reason) for f in finished.failures] == [
        ("broken", "provider", "no such model")
    ]
    assert finished.missing == [("broken", 1)]


def test_a_trial_that_takes_too_long_is_a_timeout_not_a_wrong_answer(tmp_path: Path) -> None:
    suite = make_suite(case("slow"))

    finished = run(suite, Slow(), tmp_path, RunOptions(time_limit_s=0.001))

    assert finished.results == ()
    [failure] = finished.failures
    assert failure.kind == "timeout"
    assert failure.reason == "no answer within 0.001 seconds"


def test_an_answer_from_the_wrong_model_is_a_failure(tmp_path: Path) -> None:
    suite = make_suite(case("swapped"), model="claude-sonnet-5-5")
    usage = Usage(input_tokens=1_000_000)
    provider = Scripted({"swapped": [answer(model="claude-haiku-5-5", usage=usage)]})

    finished = run(suite, provider, tmp_path)

    [failure] = finished.failures
    assert failure.kind == "served-model"
    assert failure.reason == "asked for 'claude-sonnet-5-5', but 'claude-haiku-5-5' answered"
    assert failure.cost_usd == pytest.approx(0.10)
    assert finished.cost_usd == pytest.approx(0.10)


@pytest.mark.parametrize(
    ("requested", "served", "matches"),
    [
        (None, "anything", True),
        ("claude-sonnet-5-5", "claude-sonnet-5-5", True),
        ("claude-sonnet-5-5", "claude-sonnet-5-5-20260601", True),
        ("claude-sonnet-5-5", "claude-sonnet-5-50", False),
        ("claude-sonnet-5-5", "claude-haiku-5-5", False),
    ],
)
def test_served_matches(requested: str | None, served: str, *, matches: bool) -> None:
    assert served_matches(requested, served) is matches


def test_a_budget_stops_the_run_before_it_overspends(tmp_path: Path) -> None:
    suite = make_suite(case("a"), case("b"), case("c"), model="claude-sonnet-5-5")
    usage = Usage(input_tokens=1_000, output_tokens=1_000)
    provider = Scripted(
        {name: [answer(model="claude-sonnet-5-5", usage=usage)] for name in "abc"},
        tokens=dict.fromkeys("abc", 1_000),
        charges=True,
    )

    finished = run(suite, provider, tmp_path, RunOptions(concurrency=1, budget_usd=0.03))

    assert [r.case_id for r in finished.results] == ["a", "b"]
    [failure] = finished.failures
    assert (failure.kind, failure.attempts) == ("budget", 0)
    assert failure.reason == "$0.0122 more would pass the $0.03 budget"
    assert finished.cost_usd == pytest.approx(0.024)
    assert finished.manifest.spent_usd == pytest.approx(0.024)


def test_a_budget_is_refused_up_front_when_the_model_has_no_price(tmp_path: Path) -> None:
    suite = make_suite(case("a"), model="claude-unknown-9")
    provider = Scripted({"a": [answer(model="claude-unknown-9")]}, charges=True)

    with pytest.raises(ProviderError, match="can't hold a budget for model 'claude-unknown-9'"):
        run(suite, provider, tmp_path, RunOptions(budget_usd=1.0))

    assert list(tmp_path.iterdir()) == []


def test_a_budget_means_nothing_to_a_provider_that_answers_for_free(tmp_path: Path) -> None:
    suite = make_suite(case("a"), case("b"), model="claude-sonnet-5-5")
    usage = Usage(input_tokens=1_000_000)
    provider = Scripted({name: [answer(model="claude-sonnet-5-5", usage=usage)] for name in "ab"})

    finished = run(suite, provider, tmp_path, RunOptions(budget_usd=0.001))

    assert [r.case_id for r in finished.results] == ["a", "b"]
    assert finished.failures == ()
    assert finished.manifest.spent_usd == 0.0


def test_a_paid_run_that_cannot_count_tokens_never_starts(tmp_path: Path) -> None:
    class Blind(Scripted):
        async def estimate(self, _request: Request, /) -> int:
            raise ProviderError("no Anthropic credentials found")

    suite = make_suite(case("a"), model="claude-sonnet-5-5")

    with pytest.raises(ProviderError, match="no Anthropic credentials found"):
        run(suite, Blind({"a": [answer()]}, charges=True), tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_a_request_cut_off_by_the_time_limit_is_counted_at_its_worst_case(tmp_path: Path) -> None:
    suite = make_suite(case("a"), model="claude-sonnet-5-5")

    finished = run(suite, Stuck(), tmp_path, RunOptions(time_limit_s=0.01, budget_usd=1.0))

    [failure] = finished.failures
    assert failure.kind == "timeout"
    assert failure.cost_usd is None
    assert finished.manifest.spent_usd == pytest.approx(
        cost_usd(Usage(input_tokens=1_000, output_tokens=1024), "claude-sonnet-5-5")
    )


def test_a_budget_needs_estimates_and_says_so_when_it_cannot_get_them(tmp_path: Path) -> None:
    class Blind(Scripted):
        async def estimate(self, _request: Request, /) -> int:
            raise ProviderError("couldn't count tokens")

    suite = make_suite(case("a"), model="claude-sonnet-5-5")

    with pytest.raises(ProviderError, match="couldn't count tokens"):
        run(suite, Blind({"a": [answer()]}, charges=True), tmp_path, RunOptions(budget_usd=1.0))


def test_the_budget_reserves_the_worst_case_and_settles_the_real_cost() -> None:
    budget = Budget(limit_usd=1.0)

    assert budget.reserve(0.6)
    assert not budget.reserve(0.5)
    budget.settle(0.6, 0.1)
    assert budget.reserve(0.5)
    assert budget.spent_usd == pytest.approx(0.1)
    assert Budget(limit_usd=None).reserve(1e9)


@given(
    attempt=st.integers(min_value=1, max_value=20), base=st.floats(min_value=0.001, max_value=10)
)
def test_backoff_never_exceeds_its_ceiling(attempt: int, base: float) -> None:
    wait = backoff(attempt, None, base=base)

    assert 0 <= wait <= min(BACKOFF_CAP_S, base * 2 ** (attempt - 1))


def test_backoff_honours_the_wait_the_api_asked_for_up_to_the_cap() -> None:
    assert backoff(1, 7.0, base=1.0) == 7.0
    assert backoff(1, 600.0, base=1.0) == BACKOFF_CAP_S


def test_an_interrupted_run_resumes_to_what_a_straight_run_would_have_been(
    files: Files,
) -> None:
    files.write("replies.yaml", 'a: "yes"\nb: "yes"\nc: "yes"\n')
    path = files.write(
        "suite.yaml",
        """
        schema: 1
        name: resumable
        target: {provider: fake, model: fake-1, options: {replies: replies.yaml}}
        trials: 2
        cases:
          - {id: a, input: Hi, checks: [{type: contains, text: "yes"}]}
          - {id: b, input: Hi, checks: [{type: contains, text: "yes"}]}
          - {id: c, input: Hi, checks: [{type: contains, text: "yes"}]}
        """,
    )
    suite = load_suite(path)
    out = files.root / "runs"
    straight = run(suite, FakeProvider.from_file(files.root / "replies.yaml"), out)

    class PowerCut(Scripted):
        async def complete(self, request: Request, /) -> Completion:
            if len(self.calls) == 2:
                raise RuntimeError("power cut")
            return await super().complete(request)

    cut = PowerCut({name: [answer()] * 2 for name in "abc"})
    folder = start_run(suite, Providers(cut), out=out, options=RunOptions(concurrency=1))
    with pytest.raises(ExceptionGroup):
        asyncio.run(complete_run(plan(suite, cut), folder))
    assert len(folder.answered) == 2
    assert folder.manifest.finished_at is None

    replies = FakeProvider.from_file(files.root / "replies.yaml")
    resumed = asyncio.run(resume_run(folder.path, Providers(replies)))

    assert [(r.case_id, r.trial, r.answer.text) for r in resumed.results] == [
        (r.case_id, r.trial, r.answer.text) for r in straight.results
    ]
    assert resumed.manifest.resumed == 1
    assert resumed.manifest.finished_at is not None
    assert resumed.failures == ()


def test_resuming_answers_only_the_trials_that_failed(files: Files) -> None:
    files.write("replies.yaml", 'a: "yes"\n')
    path = files.write(
        "suite.yaml",
        """
        schema: 1
        name: flaky
        target: {provider: fake, model: fake-1, options: {replies: replies.yaml}}
        trials: 3
        cases:
          - {id: a, input: Hi, checks: [{type: contains, text: "yes"}]}
        """,
    )
    suite = load_suite(path)
    first = Scripted({"a": [answer(), ProviderError("hiccup"), answer()]})
    folder = start_run(suite, Providers(first), out=files.root / "runs")
    asyncio.run(complete_run(plan(suite, first), folder))

    second = Scripted({"a": [answer("yes again")]})
    resumed = asyncio.run(resume_run(folder.path, Providers(second)))

    assert second.calls == [("a", 2)]
    assert [r.answer.text for r in resumed.results] == ["yes", "yes again", "yes"]
    assert [f.reason for f in resumed.failures] == ["hiccup"]


def test_resume_run_builds_its_own_provider_from_the_run_when_given_none(files: Files) -> None:
    files.write("replies.yaml", 'a: "yes"\n')
    path = files.write(
        "suite.yaml",
        """
        schema: 1
        name: own-provider
        target: {provider: fake, model: fake-1, options: {replies: replies.yaml}}
        trials: 2
        cases:
          - {id: a, input: Hi, checks: [{type: contains, text: "yes"}]}
        """,
    )
    suite = load_suite(path)
    first = Scripted({"a": [answer(), ProviderError("hiccup")]})
    folder = start_run(suite, Providers(first), out=files.root / "runs")
    asyncio.run(complete_run(plan(suite, first), folder))

    resumed = asyncio.run(resume_run(folder.path))

    assert [r.answer.text for r in resumed.results] == ["yes", "yes"]
    assert resumed.missing == []


def test_a_run_whose_suite_changed_cannot_be_resumed(files: Files) -> None:
    files.write("replies.yaml", 'a: "yes"\n')
    path = files.write(
        "suite.yaml",
        """
        schema: 1
        name: drifting
        target: {provider: fake, options: {replies: replies.yaml}}
        cases:
          - {id: a, input: Hi, checks: [{type: contains, text: "yes"}]}
        """,
    )
    folder = start_run(
        load_suite(path), Providers(Scripted({"a": [answer()]})), out=files.root / "runs"
    )
    path.write_text(path.read_text().replace("input: Hi", "input: Hello"), encoding="utf-8")

    with pytest.raises(RunError, match="the suite has changed since run"):
        reopen_run(folder.path)


def test_a_run_of_a_suite_built_in_code_cannot_be_resumed(tmp_path: Path) -> None:
    folder = start_run(make_suite(case("a")), Providers(Scripted({"a": [answer()]})), out=tmp_path)

    with pytest.raises(RunError, match="wasn't loaded from a file"):
        reopen_run(folder.path)


def test_a_cancelled_run_keeps_what_it_had_and_resumes_cleanly(files: Files) -> None:
    files.write("replies.yaml", 'a: "yes"\nb: "yes"\n')
    path = files.write(
        "suite.yaml",
        """
        schema: 1
        name: cancelled
        target: {provider: fake, model: fake-1, options: {replies: replies.yaml}}
        cases:
          - {id: a, input: Hi, checks: [{type: contains, text: "yes"}]}
          - {id: b, input: Hi, checks: [{type: contains, text: "yes"}]}
        """,
    )
    suite = load_suite(path)

    @dataclass
    class HalfStuck:
        charges: bool = False
        asked: asyncio.Event = field(default_factory=asyncio.Event)

        async def complete(self, request: Request, /) -> Completion:
            if request.case_id == "a":
                return answer()
            self.asked.set()
            await asyncio.Event().wait()
            raise AssertionError("never answers")

        async def estimate(self, _request: Request, /) -> int:
            return 0

        async def aclose(self) -> None:
            pass

    async def interrupted() -> RunFolder:
        provider = HalfStuck()
        folder = start_run(suite, Providers(provider), out=files.root / "runs")
        running = asyncio.create_task(complete_run(plan(suite, provider), folder))
        await provider.asked.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        return folder

    folder = asyncio.run(interrupted())
    assert folder.answered == {("a", 1)}
    assert not (folder.path / "errors.jsonl").exists()
    assert folder.manifest.finished_at is None

    resumed = asyncio.run(resume_run(folder.path, Providers(Scripted({"b": [answer()]}))))

    assert [(r.case_id, r.answer.text) for r in resumed.results] == [("a", "yes"), ("b", "yes")]
    assert resumed.failures == ()
    assert resumed.manifest.resumed == 1
    assert resumed.manifest.finished_at is not None


def test_a_live_run_can_be_replayed_without_spending_anything(tmp_path: Path) -> None:
    suite = make_suite(case("a"), case("b"), trials=2, model="claude-sonnet-5-5")
    usage = Usage(input_tokens=10, output_tokens=5)
    script = {
        name: [answer(f"{name} {n}", model="claude-sonnet-5-5", usage=usage) for n in (1, 2)]
        for name in "ab"
    }
    live = run(suite, Scripted(script, charges=True), tmp_path)

    replay = ReplayProvider.from_file(tmp_path / live.manifest.run_id / "recording.jsonl")
    replayed = run(suite, replay, tmp_path)

    assert [r.answer.text for r in replayed.results] == [r.answer.text for r in live.results]
    assert replayed.cost_usd == pytest.approx(live.cost_usd)
    assert live.manifest.charges
    assert not replayed.manifest.charges
