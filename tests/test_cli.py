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
from temper.cli import app
from tests.support import EXAMPLE

if TYPE_CHECKING:
    from pathlib import Path

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
    assert "is valid: 5 cases, 9 checks" in result.output


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
    assert "at list price, nothing spent" in result.output


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
    """A client for a pretend API that greets every request and counts a few tokens."""

    def api(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 10})
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": "Hello!"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    transport = httpx2.MockTransport(api)
    return AsyncAnthropic(**settings, http_client=DefaultAsyncHttpxClient(transport=transport))


def test_python_dash_m_temper_runs_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["temper", "--version"])

    with pytest.raises(SystemExit) as finished:
        runpy.run_module("temper", run_name="__main__")

    assert finished.value.code == 0
