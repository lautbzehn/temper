from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING

import pytest
from rich.console import Console

from temper import jsonl
from temper.errors import ProviderError, TransientError
from temper.judge import VERDICT_SCHEMA
from temper.planning import Estimates, Plan, Providers, estimate_suite, plan_run, providers_for
from temper.pricing import cost_usd
from temper.providers import ClaudeProvider, Recording, ReplayProvider, Usage
from temper.results import RunOptions
from temper.runner import complete_run, resume_run, start_run
from temper.summary import render_run
from temper.wording import dollars
from tests.support import Scripted, Slow, answer, case, judged, make_suite, plan, run, verdict

if TYPE_CHECKING:
    from pathlib import Path

    from temper.providers import Completion
    from temper.suite import Suite
    from tests.support import Files

USAGE = Usage(input_tokens=100, output_tokens=10)
ANSWER_USD = cost_usd(USAGE, "claude-sonnet-5-5") or 0.0
VERDICT_USD = cost_usd(USAGE, "claude-opus-5-5") or 0.0


def priced(*cases: dict[str, object]) -> Suite:
    return make_suite(*cases, model="claude-sonnet-5-5", judge={"model": "claude-opus-5-5"})


def sonnet(text: str = "Sorry!") -> Completion:
    return answer(text, model="claude-sonnet-5-5", usage=USAGE)


def opus(*, passed: bool, reason: str = "It says sorry.") -> Completion:
    return verdict(passed=passed, reason=reason, model="claude-opus-5-5", usage=USAGE)


def recorded_keys(out: Path, run_id: str) -> set[tuple[str, int, int | None]]:
    return {record.key for record in jsonl.read(out / run_id / "recording.jsonl", Recording)}


def test_a_judge_check_asks_the_judge_and_keeps_its_verdict_and_cost(tmp_path: Path) -> None:
    suite = priced(judged("a", "apologizes"))
    answers = Scripted({"a": [sonnet()]}, charges=True)
    judge = Scripted({"a": [opus(passed=True)]}, charges=True)

    finished = run(suite, answers, tmp_path, judge=judge)

    [result] = finished.results
    [grade] = result.grades
    assert (grade.check, grade.passed, grade.reason) == (
        'judge "apologizes"',
        True,
        "It says sorry.",
    )
    assert grade.cost_usd == pytest.approx(VERDICT_USD)
    assert result.scored
    assert result.passed is True
    assert finished.manifest.judge == "claude-opus-5-5"
    assert finished.verdicts_usd == pytest.approx(VERDICT_USD)
    assert finished.cost_usd == pytest.approx(ANSWER_USD + VERDICT_USD)
    assert finished.manifest.spent_usd == pytest.approx(ANSWER_USD + VERDICT_USD)
    [asked] = judge.requests
    assert (asked.case_id, asked.trial, asked.check, asked.model) == ("a", 1, 0, "claude-opus-5-5")
    assert asked.json_schema == VERDICT_SCHEMA
    assert "Sorry!" in asked.messages[0].content
    assert recorded_keys(tmp_path, finished.manifest.run_id) == {("a", 1, None), ("a", 1, 0)}


def test_a_judge_that_cannot_answer_leaves_no_verdict_and_the_trial_unscored(
    tmp_path: Path,
) -> None:
    judge = Scripted({"a": [ProviderError("the judge is down")]})

    finished = run(make_suite(judged("a")), Scripted({"a": [answer()]}), tmp_path, judge=judge)

    [result] = finished.results
    [grade] = result.grades
    assert (grade.passed, grade.reason) == (None, "no verdict: the judge is down")
    assert result.passed is None
    assert not result.scored
    assert finished.scored == ()
    assert finished.without_verdict == 1
    assert finished.failures == ()


def test_a_judges_passing_trouble_is_retried(tmp_path: Path) -> None:
    judge = Scripted({"a": [TransientError("busy"), verdict(passed=True)]})
    options = RunOptions(backoff_s=0.001)

    finished = run(
        make_suite(judged("a")), Scripted({"a": [answer()]}), tmp_path, options, judge=judge
    )

    [grade] = finished.results[0].grades
    assert grade.passed is True
    assert judge.calls == [("a", 1), ("a", 1)]


def test_the_judge_must_be_the_model_that_was_asked(tmp_path: Path) -> None:
    judge = Scripted({"a": [verdict(passed=True, model="judge-2")]})

    finished = run(make_suite(judged("a")), Scripted({"a": [answer()]}), tmp_path, judge=judge)

    [grade] = finished.results[0].grades
    assert grade.passed is None
    assert grade.reason == "no verdict: asked for 'judge-1', but 'judge-2' answered"


def test_a_judged_suite_needs_a_judge_that_is_not_the_model_under_test(tmp_path: Path) -> None:
    with pytest.raises(ProviderError, match="no judge was given"):
        run(make_suite(judged("a")), Scripted({"a": [answer()]}), tmp_path)
    self_judged = make_suite(judged("a"), model="judge-1")
    with pytest.raises(ProviderError, match="can't be the model under test, 'judge-1'"):
        run(self_judged, Scripted({"a": [answer()]}), tmp_path, judge=Scripted({}))


def test_a_plan_made_without_a_judge_reaches_no_verdict(tmp_path: Path) -> None:
    suite = make_suite(judged("a"))
    answers = Scripted({"a": [answer()]})
    planned = plan(suite, answers)

    finished = asyncio.run(complete_run(planned, start_run(planned, out=tmp_path)))

    [grade] = finished.results[0].grades
    assert grade.reason == "no verdict: nothing to answer from: the recording lacks this request"


def test_providers_for_sets_up_a_judge_only_when_a_check_needs_one(files: Files) -> None:
    options = {"replies": str(files.write("replies.yaml", "a: 'yes'\n"))}

    plain = providers_for(make_suite(case("a"), options=options), RunOptions())
    judging = providers_for(
        make_suite(judged("a"), options=options, judge={"model": "claude-opus-5-5"}), RunOptions()
    )

    assert plain.judge is None
    assert not plain.charges
    assert isinstance(judging.judge, ClaudeProvider)
    assert judging.recording is None
    assert judging.charges


def test_a_replay_takes_recorded_verdicts_and_asks_the_judge_only_for_the_rest(
    tmp_path: Path,
) -> None:
    suite = priced(judged("a", "apologizes"), judged("b", "apologizes"))
    answers = Scripted({"a": [sonnet()], "b": [sonnet("Nope.")]}, charges=True)
    first = Scripted(
        {"a": [opus(passed=True)], "b": [opus(passed=False, reason="No.")]}, charges=True
    )
    live = run(suite, answers, tmp_path, judge=first)
    recording = ReplayProvider.from_file(tmp_path / live.manifest.run_id / "recording.jsonl")

    idle = Scripted({}, charges=True)
    replayed = run(suite, Providers(recording, idle, recording), tmp_path)

    assert idle.calls == []
    assert [grade.passed for result in replayed.results for grade in result.grades] == [True, False]
    assert replayed.manifest.spent_usd == 0.0
    assert replayed.cost_usd == pytest.approx(live.cost_usd)
    assert recorded_keys(tmp_path, replayed.manifest.run_id) == recorded_keys(
        tmp_path, live.manifest.run_id
    )

    reworded = priced(judged("a", "says sorry"), judged("b", "says sorry"))
    fresh = Scripted({"a": [opus(passed=True)], "b": [opus(passed=True)]}, charges=True)
    rejudged = run(reworded, Providers(recording, fresh, recording), tmp_path)

    assert fresh.calls == [("a", 1), ("b", 1)]
    assert [grade.passed for result in rejudged.results for grade in result.grades] == [True, True]
    assert rejudged.manifest.spent_usd == pytest.approx(2 * VERDICT_USD)
    assert rejudged.cost_usd == pytest.approx(2 * ANSWER_USD + 2 * VERDICT_USD)


def test_a_replay_under_a_budget_pays_nothing_for_what_is_recorded(tmp_path: Path) -> None:
    suite = priced(judged("a"))
    live = run(
        suite,
        Scripted({"a": [sonnet()]}, charges=True),
        tmp_path,
        judge=Scripted({"a": [opus(passed=True)]}, charges=True),
    )
    recording = ReplayProvider.from_file(tmp_path / live.manifest.run_id / "recording.jsonl")
    idle = Scripted({}, charges=True)

    planned = asyncio.run(
        plan_run(suite, Providers(recording, idle, recording), RunOptions(budget_usd=0.001))
    )
    replayed = run(
        suite, Providers(recording, idle, recording), tmp_path, RunOptions(budget_usd=0.001)
    )

    assert planned.estimates.verdicts_on_record == 1
    assert planned.worst_verdict_usd("a", 0) == 0.0
    assert idle.calls == []
    assert [grade.passed for result in replayed.results for grade in result.grades] == [True]
    assert replayed.manifest.spent_usd == 0.0


def test_a_non_verdict_is_never_recorded_so_the_judge_is_asked_again(tmp_path: Path) -> None:
    suite = priced(judged("a"))
    unsure = Scripted({"a": [answer("Sure, pass!", model="claude-opus-5-5")]}, charges=True)
    live = run(suite, Scripted({"a": [sonnet()]}, charges=True), tmp_path, judge=unsure)
    assert live.without_verdict == 1
    assert recorded_keys(tmp_path, live.manifest.run_id) == {("a", 1, None)}

    recording = ReplayProvider.from_file(tmp_path / live.manifest.run_id / "recording.jsonl")
    fresh = Scripted({"a": [opus(passed=True)]}, charges=True)
    replayed = run(suite, Providers(recording, fresh, recording), tmp_path)

    assert fresh.calls == [("a", 1)]
    assert [grade.passed for result in replayed.results for grade in result.grades] == [True]


def test_an_interrupt_while_judging_loses_nothing_on_resume(files: Files) -> None:
    files.write("replies.yaml", "a: Sorry!\n")
    path = files.write(
        "suite.yaml",
        """
        schema: 1
        name: judged
        target: {provider: fake, model: claude-sonnet-5-5, options: {replies: replies.yaml}}
        judge: {model: claude-opus-5-5}
        cases:
          - id: a
            input: Hi
            checks:
              - {type: judge, property: apologizes}
              - {type: judge, property: is brief}
        """,
    )
    from temper.loading import load_suite  # noqa: PLC0415  (a file suite, so the run can be reopened)

    suite = load_suite(path)
    out = files.root / "runs"
    answers = Scripted({"a": [sonnet()]}, charges=True)
    cut = Scripted({"a": [opus(passed=True), RuntimeError("power cut")]}, charges=True)
    planned = plan(suite, answers, cut)
    folder = start_run(planned, out=out)
    with pytest.raises(ExceptionGroup):
        asyncio.run(complete_run(planned, folder))
    assert folder.answered == frozenset()
    assert recorded_keys(out, folder.manifest.run_id) == {("a", 1, None), ("a", 1, 0)}

    nothing = Scripted({"a": []}, charges=True)
    second = Scripted({"a": [opus(passed=False, reason="Too long.")]}, charges=True)
    resumed = asyncio.run(resume_run(folder.path, Providers(nothing, second)))

    assert nothing.calls == []
    assert second.calls == [("a", 1)]
    [result] = resumed.results
    assert [grade.passed for grade in result.grades] == [True, False]
    assert resumed.manifest.spent_usd == pytest.approx(VERDICT_USD)
    assert recorded_keys(out, folder.manifest.run_id) == {("a", 1, None), ("a", 1, 0), ("a", 1, 1)}
    assert len(list(jsonl.read(folder.path / "recording.jsonl", Recording))) == 3

    recording = ReplayProvider.from_file(folder.path / "recording.jsonl")
    idle = Scripted({}, charges=True)
    replayed = run(suite, Providers(recording, idle, recording), out)
    assert idle.calls == []
    assert [grade.passed for grade in replayed.results[0].grades] == [True, False]


def test_a_budget_covers_each_verdict_at_its_worst_case(tmp_path: Path) -> None:
    suite = priced(judged("a"))
    answers = Scripted({"a": [sonnet()]}, tokens={"a": 1_000}, charges=True)
    judge = Scripted({"a": [opus(passed=True)]}, tokens={"a": 300}, charges=True)
    providers = Providers(answers, judge)
    worst_answer = cost_usd(Usage(input_tokens=1_000, output_tokens=1024), "claude-sonnet-5-5") or 0
    worst_verdict = cost_usd(Usage(input_tokens=1_324, output_tokens=512), "claude-opus-5-5") or 0

    planned = asyncio.run(plan_run(suite, providers, RunOptions(budget_usd=5.0)))

    assert planned.estimates.answers == {"a": 1_000}
    assert planned.estimates.verdicts == {("a", 0): 300}
    assert planned.worst_answer_usd("a") == pytest.approx(worst_answer)
    assert planned.worst_verdict_usd("a", 0) == pytest.approx(worst_verdict)
    assert planned.worst_trial_usd(suite.cases[0]) == pytest.approx(worst_answer + worst_verdict)

    # Room for the answer at its worst, and for what it really cost, but not for a verdict too.
    tight = RunOptions(budget_usd=worst_answer + worst_verdict / 10)
    finished = run(suite, providers, tmp_path, tight)

    [result] = finished.results
    [grade] = result.grades
    assert grade.passed is None
    assert grade.reason.startswith("no verdict: $")
    assert "would pass the" in grade.reason
    assert judge.calls == []
    assert finished.manifest.spent_usd == pytest.approx(ANSWER_USD)


def test_a_budget_needs_a_price_for_the_judge_too() -> None:
    suite = make_suite(judged("a"), model="claude-sonnet-5-5")
    providers = Providers(Scripted({}, charges=True), Scripted({}, charges=True))

    with pytest.raises(ProviderError, match="can't hold a budget for model 'judge-1'"):
        asyncio.run(plan_run(suite, providers, RunOptions(budget_usd=1.0)))


def test_a_model_with_no_name_has_no_ceiling() -> None:
    suite = make_suite(case("a"), model=None)

    planned = Plan(suite, Providers(Scripted({}, charges=True)), RunOptions(), Estimates(), None)

    assert planned.worst_answer_usd("a") == 0.0


def test_every_live_request_is_counted_first_and_a_replay_counts_nothing_live() -> None:
    suite = make_suite(judged("a"))
    live = Scripted({}, charges=True)
    planned = asyncio.run(plan_run(suite, Providers(Scripted({}), live), RunOptions()))
    [counted] = live.estimated
    assert (counted.case_id, counted.check) == ("a", 0)
    assert planned.estimates.verdicts == {("a", 0): 0}
    assert "\n\n</answer-" in counted.messages[0].content

    replayed = Scripted({}, charges=True)
    recording = ReplayProvider([])
    asyncio.run(plan_run(suite, Providers(recording, replayed, recording), RunOptions()))
    assert replayed.estimated == []

    spare = Scripted({}, charges=True)
    asyncio.run(plan_run(make_suite(case("a")), Providers(Scripted({}), spare), RunOptions()))
    assert spare.estimated == []


def test_verdicts_on_record_are_not_counted_and_the_rest_are_counted_whole(tmp_path: Path) -> None:
    suite = priced(judged("a", "apologizes"))
    live = run(
        suite,
        Scripted({"a": [sonnet("Sorry!")]}, charges=True),
        tmp_path,
        judge=Scripted({"a": [opus(passed=True)]}, charges=True),
    )
    recording = ReplayProvider.from_file(tmp_path / live.manifest.run_id / "recording.jsonl")
    judge = Scripted({}, charges=True, tokens={"a": 999})

    held = asyncio.run(estimate_suite(suite, Providers(recording, judge, recording), RunOptions()))
    reworded = priced(judged("a", "says sorry"))
    asked = asyncio.run(
        estimate_suite(reworded, Providers(recording, judge, recording), RunOptions())
    )

    assert (held.estimates.verdicts_on_record, held.estimates.verdicts) == (1, {})
    assert held.budget_usd is None
    assert (asked.estimates.verdicts_on_record, asked.estimates.verdicts) == (0, {("a", 0): 999})
    [counted] = judge.estimated
    assert "Sorry!" in counted.messages[0].content


def test_the_summary_counts_answers_with_no_verdict_and_the_judges_share(tmp_path: Path) -> None:
    suite = priced(judged("a"), judged("b"))
    answers = Scripted({"a": [sonnet()], "b": [sonnet()]}, charges=True)
    judge = Scripted({"a": [opus(passed=True)], "b": [ProviderError("down")]}, charges=True)
    finished = run(suite, answers, tmp_path, judge=judge)
    buffer = io.StringIO()

    render_run(finished, Console(file=buffer, width=120))

    shown = buffer.getvalue()
    assert "test · fake claude-sonnet-5-5 · judge claude-opus-5-5 · 2 cases × 1 trial" in shown
    assert "1 of 1 scored trial passed (100%," in shown
    assert "trial 1: no verdict: down" in shown
    assert f"spent, {dollars(VERDICT_USD)} of it on the judge" in shown


def test_a_cost_check_with_no_price_leaves_the_trial_unscored(tmp_path: Path) -> None:
    suite = make_suite(case("a", {"type": "cost", "max_usd": 0.01}))

    finished = run(suite, Scripted({"a": [answer()]}), tmp_path)

    [grade] = finished.results[0].grades
    assert grade.passed is None
    assert finished.without_verdict == 1
    assert finished.scored == ()


def test_a_replayed_answer_keeps_its_recorded_latency(tmp_path: Path) -> None:
    suite = make_suite(case("a"), model="slow")
    live = run(suite, Slow(charges=True), tmp_path)
    [timed] = live.results
    assert timed.latency_ms >= 40

    recording = ReplayProvider.from_file(tmp_path / live.manifest.run_id / "recording.jsonl")
    replayed = run(suite, recording, tmp_path)

    assert replayed.results[0].latency_ms == timed.latency_ms


def test_the_judge_sees_the_whole_conversation_but_not_the_system_prompt(tmp_path: Path) -> None:
    turns = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "Where is my order?"},
    ]
    talk = {"id": "a", "messages": turns, "checks": [{"type": "judge", "property": "helps"}]}
    plain = make_suite(talk)
    suite = plain.model_copy(
        update={"target": plain.target.model_copy(update={"system": "TOP SECRET"})}
    )
    judge = Scripted({"a": [verdict(passed=True)]})

    run(suite, Scripted({"a": [answer("On its way.")]}, charges=False), tmp_path, judge=judge)

    [asked] = judge.requests
    question = asked.messages[0].content
    assert question.index("Hi") < question.index("Hello") < question.index("Where is my order?")
    assert "TOP SECRET" not in question
    assert asked.system is not None
    assert "TOP SECRET" not in asked.system
