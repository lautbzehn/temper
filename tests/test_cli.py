from __future__ import annotations

import json
import runpy
import sys
from typing import TYPE_CHECKING, Any

import httpx2
import pytest
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient
from typer.testing import CliRunner

from temper import __version__
from temper.checks import check_kinds
from temper.cli import app
from temper.errors import PluginError
from tests.support import EXAMPLE, local_api

if TYPE_CHECKING:
    from pathlib import Path

    from temper.plugins import Plugin
    from tests.support import Files

runner = CliRunner()

SECRET = "sk-ant-SENTINEL-never-on-disk"  # noqa: S105  (a made-up key the tests watch for)


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"temper {__version__}\n"


def test_no_arguments_shows_help() -> None:
    assert "Usage" in runner.invoke(app, []).output


def test_validate_confirms_a_good_suite() -> None:
    result = runner.invoke(app, ["validate", str(EXAMPLE)])

    assert result.exit_code == 0
    assert "is valid: 5 cases, 10 checks" in result.output


def test_validate_lists_problems_and_fails(files: Files) -> None:
    path = files.write("suite.yaml", "schema: 1\nname: thin\n")

    result = runner.invoke(app, ["validate", str(path)])

    assert result.exit_code == 1
    assert f"{path}:1:1: missing required field 'target'" in result.output


def test_run_grades_the_example_and_keeps_the_results(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", str(EXAMPLE), "--out", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "14 of 15 scored trials passed (93%)" in result.output
    assert 'trial 2: never says "sorry"' in result.output
    [folder] = tmp_path.iterdir()
    assert {path.name for path in folder.iterdir()} == {"manifest.json", "results.jsonl"}


def test_run_can_change_the_number_of_trials(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", str(EXAMPLE), "--trials", "1", "--out", str(tmp_path)])

    assert "5 of 5 scored trials passed (100%)" in result.output


def suite_with(files: Files, replies: str, *, cases: str, trials: int = 1) -> Path:
    files.write("replies.yaml", replies)
    return files.write(
        "suite.yaml",
        f"""
        schema: 1
        name: small
        target: {{provider: fake, model: fake-1, options: {{replies: replies.yaml}}}}
        trials: {trials}
        cases:
        {cases}
        """,
    )


def test_run_keeps_going_past_a_failed_trial_and_says_how_to_resume(files: Files) -> None:
    path = suite_with(
        files,
        "answered: yes please\n",
        cases="""
          - {id: answered, input: Hi, checks: [{type: contains, text: please}]}
          - {id: forgotten, input: Hi, checks: [{type: contains, text: please}]}""",
    )
    out = files.root / "runs"

    result = runner.invoke(app, ["run", str(path), "--out", str(out)])

    assert result.exit_code == 2
    assert "1 of 1 scored trial passed (100%)" in result.output
    assert "1 attempt failed: provider" in result.output
    assert "Try the unanswered trials again with: temper resume" in result.output
    [folder] = out.iterdir()
    assert json.loads((folder / "errors.jsonl").read_text())["reason"] == (
        "no fake reply for case 'forgotten'"
    )


def test_resume_answers_what_is_missing_and_finishes_the_run(files: Files) -> None:
    path = suite_with(
        files,
        "answered: yes please\n",
        cases="""
          - {id: answered, input: Hi, checks: [{type: contains, text: please}]}
          - {id: forgotten, input: Hi, checks: [{type: contains, text: please}]}""",
    )
    out = files.root / "runs"
    runner.invoke(app, ["run", str(path), "--out", str(out)])
    [folder] = out.iterdir()
    files.write("replies.yaml", "answered: yes please\nforgotten: yes please\n")

    result = runner.invoke(app, ["resume", str(folder)])

    assert result.exit_code == 0, result.output
    assert "2 of 2 scored trials passed (100%)" in result.output


def test_resume_refuses_a_folder_that_is_not_a_run(tmp_path: Path) -> None:
    result = runner.invoke(app, ["resume", str(tmp_path)])

    assert result.exit_code == 1
    assert "isn't a run Temper can read" in result.output


def test_run_reports_a_case_that_never_passed(files: Files) -> None:
    path = suite_with(
        files,
        "stubborn: nope\n",
        cases='  - {id: stubborn, input: Hi, checks: [{type: contains, text: "yes"}]}',
        trials=2,
    )

    result = runner.invoke(app, ["run", str(path), "--out", str(files.root / "runs")])

    assert result.exit_code == 0
    assert "0/2" in result.output
    assert "0 of 2 scored trials passed (0%)" in result.output


def test_run_stops_before_running_when_runs_cannot_be_kept(files: Files) -> None:
    blocker = files.write("runs", "a file where the runs folder should be")

    result = runner.invoke(app, ["run", str(EXAMPLE), "--out", str(blocker)])

    assert result.exit_code == 1
    assert f"can't keep runs in {str(blocker)!r}" in result.output


def test_a_run_that_cannot_begin_keeps_nothing(
    files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = claude_suite(files)
    out = files.root / "runs"
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(files.root))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(files.root))

    result = runner.invoke(app, ["run", str(path), "--out", str(out)])

    assert result.exit_code == 1
    assert "run stopped before it began, so nothing was kept: no Anthropic credentials found" in (
        result.output
    )
    assert not out.exists()


def test_an_interrupt_before_the_run_begins_keeps_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def interrupted(*_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("temper.cli.plan_run", interrupted)
    out = tmp_path / "runs"

    result = runner.invoke(app, ["run", str(EXAMPLE), "--out", str(out)])

    assert result.exit_code == 130
    assert "interrupted before the run began, so nothing was kept" in result.output
    assert not out.exists()


def test_an_interrupted_run_says_where_it_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def interrupted(*_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("temper.cli.complete_run", interrupted)

    result = runner.invoke(app, ["run", str(EXAMPLE), "--out", str(tmp_path)])

    assert result.exit_code == 130
    assert "interrupted; what finished is kept. Pick it up with: temper resume" in result.output


def test_a_dry_run_prices_the_worst_case_and_runs_nothing(files: Files) -> None:
    path = suite_with(
        files,
        'a: "yes"\n',
        cases='  - {id: a, input: Hi, checks: [{type: contains, text: "yes"}]}',
        trials=3,
    )

    result = runner.invoke(app, ["run", str(path), "--dry-run", "--out", str(files.root / "runs")])

    assert result.exit_code == 0, result.output
    assert "The fake provider answers for free; nothing to spend." in result.output
    assert "At most $" not in result.output
    assert not (files.root / "runs").exists()


def test_a_dry_run_prices_a_paid_provider(files: Files, monkeypatch: pytest.MonkeyPatch) -> None:
    path = claude_suite(files)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)

    result = runner.invoke(app, ["run", str(path), "--dry-run", "--trials", "2"])

    assert result.exit_code == 0, result.output
    assert "$0.0103" in result.output
    assert "At most $0.0205 for 2 trials, with every answer priced at the 1024-token ceiling." in (
        result.output
    )


def test_a_dry_run_says_when_the_model_has_no_price(
    files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = claude_suite(files, model="claude-unknown-9")
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)

    result = runner.invoke(app, ["run", str(path), "--dry-run"])

    assert "No list price for model 'claude-unknown-9'." in result.output


def test_resume_reports_a_suite_file_that_no_longer_loads(files: Files) -> None:
    path = suite_with(
        files,
        'a: "yes"\n',
        cases='  - {id: a, input: Hi, checks: [{type: contains, text: "yes"}]}',
    )
    out = files.root / "runs"
    runner.invoke(app, ["run", str(path), "--out", str(out)])
    [folder] = out.iterdir()
    path.write_text("schema: 1\nname: broken\n", encoding="utf-8")

    result = runner.invoke(app, ["resume", str(folder)])

    assert result.exit_code == 1
    assert f"{path}:1:1: missing required field 'target'" in result.output


def test_resume_keeps_what_it_has_when_the_provider_cannot_start(
    files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = claude_suite(files, cases=2)
    out = files.root / "runs"
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)
    runner.invoke(app, ["run", str(path), "--out", str(out), "--trials", "1"])
    [folder] = out.iterdir()
    (folder / "results.jsonl").write_text(
        (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()[0] + "\n",
        encoding="utf-8",
    )
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(files.root))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(files.root))

    result = runner.invoke(app, ["resume", str(folder)])

    assert result.exit_code == 1
    assert "the run wasn't picked up: no Anthropic credentials found" in result.output
    assert (folder / "results.jsonl").exists()


def test_a_budget_on_an_unpriced_model_is_refused_before_anything_is_kept(
    files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = claude_suite(files, model="claude-unknown-9")
    out = files.root / "runs"
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)

    result = runner.invoke(app, ["run", str(path), "--out", str(out), "--budget", "1"])

    assert result.exit_code == 1
    assert "run stopped before it began, so nothing was kept: can't hold a budget" in result.output
    assert not out.exists()


def test_an_unexpected_error_still_says_where_the_run_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def broken(*_: object) -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr("temper.cli.complete_run", broken)

    result = runner.invoke(app, ["run", str(EXAMPLE), "--out", str(tmp_path)])

    assert isinstance(result.exception, RuntimeError)
    assert "Stopped by an unexpected error. What finished is kept." in result.output


def test_a_run_can_be_replayed_from_a_recording(
    files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = claude_suite(files)
    out = files.root / "runs"
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)
    runner.invoke(app, ["run", str(path), "--out", str(out)])
    [folder] = out.iterdir()
    monkeypatch.delenv("ANTHROPIC_API_KEY")

    result = runner.invoke(
        app, ["run", str(path), "--out", str(out), "--replay", str(folder / "recording.jsonl")]
    )

    assert result.exit_code == 0, result.output
    assert "small · replay claude-sonnet-5-5" in result.output
    assert "at list price · nothing spent" in result.output


def test_the_api_key_never_reaches_any_kept_file(
    files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = claude_suite(files)
    out = files.root / "runs"
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)

    result = runner.invoke(app, ["run", str(path), "--out", str(out), "--budget", "1"])

    assert result.exit_code == 0, result.output
    assert "$0.0001 spent" in result.output
    assert SECRET not in result.output
    [folder] = out.iterdir()
    assert {p.name for p in folder.iterdir()} == {
        "manifest.json",
        "results.jsonl",
        "recording.jsonl",
    }
    for kept in folder.iterdir():
        assert SECRET not in kept.read_text(encoding="utf-8"), kept.name


def test_a_paid_run_answers_every_trial_on_the_first_attempt(
    files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command runs its free preflight and its trials in one event loop.

    Over real connections, a second loop would find the client's pooled
    connections bound to the first, and every trial's first attempt would
    fail and retry. A mock transport can't see that; a local socket can.
    """
    path = claude_suite(files, cases=3)
    out = files.root / "runs"
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    with local_api() as base_url:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", base_url)

        result = runner.invoke(app, ["run", str(path), "--out", str(out), "--budget", "1"])

    assert result.exit_code == 0, result.output
    [folder] = out.iterdir()
    lines = (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()
    attempts = [json.loads(line)["attempts"] for line in lines]
    assert attempts == [1, 1, 1]


def claude_suite(files: Files, *, model: str = "claude-sonnet-5-5", cases: int = 1) -> Path:
    listed = "\n".join(
        f"          - {{id: {name}, input: Hi, checks: [{{type: contains, text: hello}}]}}"
        for name in "abcdef"[:cases]
    )
    return files.write(
        "suite.yaml",
        f"""
        schema: 1
        name: small
        target: {{provider: claude, model: {model}, system: Be brief.}}
        cases:
{listed}
        """,
    )


def mock_client(**settings: Any) -> AsyncAnthropic:
    """A client for a pretend API: it greets, or gives a passing verdict when asked for JSON."""

    def api(request: httpx2.Request) -> httpx2.Response:
        asked = json.loads(request.content)
        if request.url.path.endswith("count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 10})
        shaped = "format" in asked.get("output_config", {})
        text = '{"reason": "It greets.", "passed": true}' if shaped else "Hello!"
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": asked["model"],
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    transport = httpx2.MockTransport(api)
    return AsyncAnthropic(**settings, http_client=DefaultAsyncHttpxClient(transport=transport))


def judged_suite(files: Files) -> Path:
    return files.write(
        "suite.yaml",
        """
        schema: 1
        name: judged
        target: {provider: claude, model: claude-sonnet-5-5, system: Be brief.}
        cases:
          - id: a
            input: Hi
            checks:
              - {type: contains, text: hello}
              - {type: judge, property: greets the customer}
        """,
    )


def judged_run(files: Files, monkeypatch: pytest.MonkeyPatch, *extra: str) -> Path:
    """A judged run through the pretend API; returns its folder."""
    out = files.root / "runs"
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)
    result = runner.invoke(app, ["run", str(judged_suite(files)), "--out", str(out), *extra])
    assert result.exit_code == 0, result.output
    [folder] = out.iterdir()
    return folder


def test_a_judged_run_asks_the_judge_and_says_what_it_cost(
    files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = files.root / "runs"
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)

    result = runner.invoke(app, ["run", str(judged_suite(files)), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert "judged · claude claude-sonnet-5-5 · judge claude-opus-5-5 · 1 case" in result.output
    assert "1 of 1 scored trial passed (100%)" in result.output
    assert "of it on the judge" in result.output
    [folder] = out.iterdir()
    recorded = [json.loads(line) for line in (folder / "recording.jsonl").read_text().splitlines()]
    assert {(r["case_id"], r["trial"], r["check"]) for r in recorded} == {
        ("a", 1, None),
        ("a", 1, 1),
    }


def test_a_dry_run_counts_the_verdicts_too(files: Files, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)

    result = runner.invoke(app, ["run", str(judged_suite(files)), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Judge calls" in result.output
    assert "every answer priced at the 1024-token ceiling and every verdict at the judge's" in (
        result.output
    )


def test_labels_are_asked_for_blind_and_then_calibrated(
    files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = judged_run(files, monkeypatch)

    labeled = runner.invoke(app, ["label", str(folder)], input="y\n")

    assert labeled.exit_code == 0, labeled.output
    assert "Does the answer have this property? [y]es, [n]o, [s]kip, [q]uit:" in labeled.output
    assert "Property: greets the customer" in labeled.output
    assert "It greets." not in labeled.output
    assert "1 label added; every judged answer is labeled. Next: temper calibrate" in labeled.output

    again = runner.invoke(app, ["label", str(folder)])
    assert "Nothing to label" in again.output

    calibrated = runner.invoke(app, ["calibrate", str(folder)])
    assert calibrated.exit_code == 0, calibrated.output
    assert "judged · judge claude-opus-5-5 · 1 label met a verdict" in calibrated.output
    assert "Agreement 100% (1 of 1)" in calibrated.output
    assert "Too few labels to say: 1 of the 20 it takes." in calibrated.output

    elsewhere = runner.invoke(app, ["calibrate", str(folder), "--labels", str(folder / "gone")])
    assert elsewhere.exit_code == 1
    assert "no labels file at" in elsewhere.output


def test_calibrate_wants_labels_first(files: Files, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = judged_run(files, monkeypatch)

    result = runner.invoke(app, ["calibrate", str(folder)])

    assert result.exit_code == 1
    assert f"no labels to compare with; make some with: temper label {folder}" in result.output


def test_labeling_can_stop_early_and_keeps_what_it_has(
    files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = judged_run(files, monkeypatch, "--trials", "2")

    stopped = runner.invoke(app, ["label", str(folder)], input="n\n")

    assert stopped.exit_code == 130
    assert "stopped; every label given so far is kept" in stopped.output
    assert len((folder / "labels.jsonl").read_text().splitlines()) == 1

    quit_ = runner.invoke(app, ["label", str(folder)], input="q\n")
    assert quit_.exit_code == 0
    assert f"0 labels added, 1 to go. Pick it up with: temper label {folder}" in quit_.output

    disagreed = runner.invoke(app, ["calibrate", str(folder)])
    assert "Agreement 0% (0 of 1)" in disagreed.output
    assert "judge: pass, you: fail · the judge said: It greets." in disagreed.output
    assert "Too few labels to say" in disagreed.output


def test_a_replayed_dry_run_says_which_verdicts_are_on_record(
    files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = judged_run(files, monkeypatch)
    recording = str(folder / "recording.jsonl")

    held = runner.invoke(app, ["run", str(judged_suite(files)), "--replay", recording, "--dry-run"])

    assert held.exit_code == 0, held.output
    assert "1 of 1 verdict are in the recording" in held.output
    assert "Nothing to spend." in held.output

    suite = judged_suite(files)
    suite.write_text(suite.read_text().replace("greets the customer", "says hello"))
    asked = runner.invoke(app, ["run", str(suite), "--replay", recording, "--dry-run"])

    assert asked.exit_code == 0, asked.output
    assert "0 of 1 verdict are in the recording" in asked.output
    assert "At most $" in asked.output


def test_a_plugin_that_cannot_be_used_is_reported_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(group: str) -> list[Plugin]:
        raise PluginError(f"plugin 'shout' from shouty can't be loaded: no module named {group}")

    check_kinds.cache_clear()
    monkeypatch.setattr("temper.plugins.load", broken)

    result = runner.invoke(app, ["validate", str(EXAMPLE)])

    assert result.exit_code == 1
    assert "plugin 'shout' from shouty can't be loaded: no module named temper.graders" in (
        result.output
    )


def test_python_dash_m_temper_runs_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["temper", "--version"])

    with pytest.raises(SystemExit) as finished:
        runpy.run_module("temper", run_name="__main__")

    assert finished.value.code == 0
