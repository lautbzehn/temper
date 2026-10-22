from __future__ import annotations

import runpy
import sys
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from temper import ProviderError, __version__
from temper.cli import app
from tests.support import EXAMPLE

if TYPE_CHECKING:
    from pathlib import Path

    from tests.support import Files

runner = CliRunner()


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
    assert "14 of 15 trials passed (93%)" in result.output
    assert 'trial 2: never says "sorry"' in result.output
    [folder] = tmp_path.iterdir()
    assert {path.name for path in folder.iterdir()} == {"manifest.json", "results.jsonl"}


def test_run_can_change_the_number_of_trials(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", str(EXAMPLE), "--trials", "1", "--out", str(tmp_path)])

    assert "5 of 5 trials passed (100%)" in result.output


def test_run_stops_with_a_clear_message_when_a_reply_is_missing(files: Files) -> None:
    files.write("replies.yaml", "answered: yes please\n")
    path = files.write(
        "suite.yaml",
        """
        schema: 1
        name: gap
        target: {provider: fake, options: {replies: replies.yaml}}
        cases:
          - {id: answered, input: Hi, checks: [{type: contains, text: please}]}
          - {id: forgotten, input: Hi, checks: [{type: contains, text: please}]}
        """,
    )

    result = runner.invoke(app, ["run", str(path), "--out", str(files.root / "runs")])

    assert result.exit_code == 1
    assert "run stopped: no fake reply for case 'forgotten'" in result.output


def test_run_reports_a_case_that_never_passed(files: Files) -> None:
    files.write("replies.yaml", "stubborn: nope\n")
    path = files.write(
        "suite.yaml",
        """
        schema: 1
        name: stubborn
        target: {provider: fake, options: {replies: replies.yaml}}
        trials: 2
        cases:
          - {id: stubborn, input: Hi, checks: [{type: contains, text: "yes"}]}
        """,
    )

    result = runner.invoke(app, ["run", str(path), "--out", str(files.root / "runs")])

    assert result.exit_code == 0
    assert "0/2" in result.output
    assert "0 of 2 trials passed (0%)" in result.output


def test_run_stops_before_running_when_runs_cannot_be_kept(files: Files) -> None:
    blocker = files.write("runs", "a file where the runs folder should be")

    result = runner.invoke(app, ["run", str(EXAMPLE), "--out", str(blocker)])

    assert result.exit_code == 1
    assert f"can't keep runs in {str(blocker)!r}" in result.output


@pytest.mark.parametrize(
    "errors",
    [
        [RuntimeError("a real bug")],
        [ProviderError("rate limited"), RuntimeError("a real bug")],
    ],
)
def test_unexpected_errors_are_never_swallowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, errors: list[Exception]
) -> None:
    async def broken(*_: object, **__: object) -> None:
        raise ExceptionGroup("boom", errors)

    monkeypatch.setattr("temper.cli.run_suite", broken)

    result = runner.invoke(app, ["run", str(EXAMPLE), "--out", str(tmp_path)])

    assert isinstance(result.exception, ExceptionGroup)
    assert result.exception.subgroup(RuntimeError) is not None


def test_python_dash_m_temper_runs_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["temper", "--version"])

    with pytest.raises(SystemExit) as finished:
        runpy.run_module("temper", run_name="__main__")

    assert finished.value.code == 0
