from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import pytest
from rich.console import Console

from temper import jsonl
from temper.errors import RunError
from temper.graders import Answer, Grade
from temper.planning import Providers
from temper.providers import FakeProvider, Recording, Request, Usage
from temper.results import Manifest, Run, RunFolder, RunOptions, TrialResult
from temper.runner import manifest_for
from temper.stats import Rate
from temper.summary import render_run
from tests.support import Scripted, answer, case, make_suite, run, verdict

if TYPE_CHECKING:
    from pathlib import Path


def sample_run(out: Path) -> Run:
    suite = make_suite(case("steady"), case("wobbly"), trials=2)
    provider = FakeProvider({"steady": ["yes"], "wobbly": ["yes", "no"]})
    return run(suite, provider, out)


def test_trials_group_by_case_in_suite_order(tmp_path: Path) -> None:
    grouped = sample_run(tmp_path).by_case()

    assert list(grouped) == ["steady", "wobbly"]
    assert [[r.passed for r in results] for results in grouped.values()] == [
        [True, True],
        [True, False],
    ]


def test_a_run_counts_what_it_scored(tmp_path: Path) -> None:
    finished = sample_run(tmp_path)

    assert finished.trials_passed == 3
    assert len(finished.scored) == 4
    assert finished.missing == []
    assert finished.cost_usd is None
    assert finished.manifest.spent_usd == 0.0


def test_a_run_tells_complete_answers_from_cut_off_and_refused_ones(tmp_path: Path) -> None:
    suite = make_suite(case("mixed"), trials=3, model="claude-sonnet-5-5")
    provider = Scripted(
        {
            "mixed": [
                answer("yes", model="claude-sonnet-5-5", usage=Usage(input_tokens=1_000_000)),
                answer("yes", model="claude-sonnet-5-5", status="truncated"),
                answer("", model="claude-sonnet-5-5", status="refused"),
            ]
        }
    )

    finished = run(suite, provider, tmp_path)

    assert len(finished.scored) == 1
    assert (finished.count("truncated"), finished.count("refused")) == (1, 1)
    assert finished.cost_usd == pytest.approx(2.0)


def test_a_kept_run_reads_back_the_same(tmp_path: Path) -> None:
    finished = sample_run(tmp_path)

    folder = tmp_path / finished.manifest.run_id
    with (folder / "results.jsonl").open("a", encoding="utf-8") as lines:
        lines.write("\n\n")

    reopened = RunFolder.open(folder).run()

    assert reopened == finished
    assert reopened.manifest.finished_at is not None


def test_each_result_line_is_plain_json_with_the_whole_transcript(tmp_path: Path) -> None:
    finished = sample_run(tmp_path)
    lines = (tmp_path / finished.manifest.run_id / "results.jsonl").read_text().splitlines()

    first = json.loads(lines[0])

    assert first["request"]["messages"] == [{"role": "user", "content": "A question for steady"}]
    assert first["completion"]["text"] == "yes"
    assert first["grades"] == [
        {"check": 'contains "yes"', "passed": True, "reason": 'says "yes"', "cost_usd": None}
    ]


def test_results_come_back_in_suite_order_however_they_were_added(tmp_path: Path) -> None:
    suite = make_suite(case("steady"), case("wobbly"), trials=2)
    folder = RunFolder.start(
        tmp_path, manifest_for(suite, Providers(FakeProvider({})), RunOptions())
    )
    finished = sample_run(tmp_path)
    for result in reversed(finished.results):
        folder.add(result)

    kept = folder.run()

    assert [(r.case_id, r.trial) for r in kept.results] == [
        (r.case_id, r.trial) for r in finished.results
    ]
    assert folder.answered == {("steady", 1), ("steady", 2), ("wobbly", 1), ("wobbly", 2)}


def test_a_recording_is_kept_only_when_the_run_spent_money(tmp_path: Path) -> None:
    suite = make_suite(case("case"), model="claude-sonnet-5-5")
    paid = run(
        suite, Scripted({"case": [answer(model="claude-sonnet-5-5")]}, charges=True), tmp_path
    )
    free = run(suite, Scripted({"case": [answer(model="claude-sonnet-5-5")]}), tmp_path)

    assert (tmp_path / paid.manifest.run_id / "recording.jsonl").exists()
    assert not (tmp_path / free.manifest.run_id / "recording.jsonl").exists()


def test_a_folder_that_is_not_a_run_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RunError, match="isn't a run Temper can read"):
        RunFolder.open(tmp_path)


def test_a_run_with_a_record_temper_cannot_read_is_an_error(tmp_path: Path) -> None:
    finished = sample_run(tmp_path)
    folder = tmp_path / finished.manifest.run_id
    (folder / "results.jsonl").write_text('{"not": "a result"}\n', encoding="utf-8")

    with pytest.raises(RunError, match="holds a record Temper can't read"):
        RunFolder.open(folder)


def test_the_manifest_lists_every_slot_in_suite_order(tmp_path: Path) -> None:
    manifest = Manifest.model_validate_json(
        (tmp_path / sample_run(tmp_path).manifest.run_id / "manifest.json").read_text()
    )

    assert manifest.slots == [("steady", 1), ("steady", 2), ("wobbly", 1), ("wobbly", 2)]
    assert manifest.provider == "fake"
    assert not manifest.charges


def test_a_check_without_a_verdict_keeps_the_trial_out_of_the_score(tmp_path: Path) -> None:
    [result, *_] = sample_run(tmp_path).results
    unsure = Grade(check='judge "p"', passed=None, reason="no verdict: down", cost_usd=0.01)
    unjudged = result.model_copy(update={"grades": (unsure, *result.grades)})

    assert result.graded
    assert result.scored
    assert not unjudged.graded
    assert not unjudged.scored
    assert unjudged.verdicts_usd == 0.01
    assert unjudged.answer == Answer(
        text="yes", conversation=result.request.messages, latency_ms=result.latency_ms
    )


def test_a_recording_keeps_each_completion_and_how_long_it_took(tmp_path: Path) -> None:
    suite = make_suite(case("a"), model="claude-sonnet-5-5")
    manifest = manifest_for(suite, Providers(Scripted({}, charges=True)), RunOptions())
    folder = RunFolder.start(tmp_path, manifest)
    asked = Request(
        case_id="a",
        trial=1,
        model="claude-sonnet-5-5",
        system=None,
        messages=suite.cases[0].conversation,
        max_tokens=8,
    )
    answered = TrialResult(
        request=asked, completion=answer(model="claude-sonnet-5-5"), grades=(), latency_ms=12.5
    )

    assert not folder.recorded().has(asked)
    folder.add(answered)
    folder.record(asked, answered.completion, 12.5)
    folder.record(asked.model_copy(update={"check": 0}), verdict(passed=True), 3.0)

    recorded = list(jsonl.read(folder.path / "recording.jsonl", Recording))
    assert [(r.check, r.completion.latency_ms) for r in recorded] == [(None, 12.5), (0, 3.0)]
    assert folder.recorded().has(asked)


def test_a_run_folder_with_a_manifest_that_is_not_json_says_so(tmp_path: Path) -> None:
    folder = tmp_path / sample_run(tmp_path).manifest.run_id
    (folder / "manifest.json").write_text("{]", encoding="utf-8")

    with pytest.raises(RunError, match="holds a manifest Temper can't read"):
        RunFolder.open(folder)


def test_a_run_folder_with_a_bad_line_says_which_line(tmp_path: Path) -> None:
    folder = tmp_path / sample_run(tmp_path).manifest.run_id
    (folder / "results.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RunError, match=r"line 1 of .*results\.jsonl"):
        RunFolder.open(folder)


def test_a_run_knows_its_rates_and_its_flaky_cases(tmp_path: Path) -> None:
    finished = sample_run(tmp_path)

    assert finished.rate == Rate(3, 4)
    assert finished.rates == {"steady": Rate(2, 2), "wobbly": Rate(1, 2)}
    assert finished.flaky == ("wobbly",)
    assert finished.manifest.cases_fingerprint is not None


def test_a_run_with_nothing_scored_still_has_a_summary(tmp_path: Path) -> None:
    finished = sample_run(tmp_path).model_copy(update={"results": ()})
    buffer = io.StringIO()

    render_run(finished, Console(file=buffer, width=120))

    assert "0 of 0 scored trials passed" in buffer.getvalue()
    assert "within noise" not in buffer.getvalue()
