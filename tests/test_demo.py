from __future__ import annotations

import asyncio
import shutil
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from temper import demo
from temper.cli import app
from temper.loading import load_suite

if TYPE_CHECKING:
    from pathlib import Path

    from temper.results import Run

BROKEN = (
    "unopened-return",
    "sealed-boxes-back",
    "wet-paper-replacement",
    "crushed-box",
    "refund-to-card",
    "refund-or-lawyer",
    "promised-discount",
    "manager-approved",
    "discount-code",
)


@pytest.fixture(scope="module")
def story(tmp_path_factory: pytest.TempPathFactory) -> demo.Story:
    return asyncio.run(demo.replay(tmp_path_factory.mktemp("story")))


def fully_replayed(run: Run) -> None:
    """Every trial answered and every check decided from the recording, none of it live."""
    assert run.failures == ()
    assert run.missing == []
    assert run.without_verdict == 0
    assert run.manifest.spent_usd == 0.0


def test_the_story_replays_whole_from_its_recording(story: demo.Story) -> None:
    fully_replayed(story.baseline)
    fully_replayed(story.candidate)
    assert not story.baseline.manifest.charges
    assert story.baseline.manifest.options.system is None
    assert story.candidate.manifest.options.system == demo.TIDY_UP


def test_the_tidy_up_breaks_refunds_and_honors_a_discount_nobody_offered(story: demo.Story) -> None:
    compared = story.comparison

    assert story.baseline.rate.passed == story.baseline.rate.scored == 200
    assert compared.finding == "worse"
    assert not compared.ship
    assert tuple(change.case_id for change in compared.regressed) == BROKEN
    assert compared.improved == ()


def test_the_demo_command_needs_no_key_and_writes_the_scorecard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    card = tmp_path / "story.html"

    result = CliRunner().invoke(app, ["demo", "--out", str(card)])

    assert result.exit_code == 0, result.output
    assert "Hold: 9 cases got worse beyond noise: unopened-return" in result.output
    assert "system dwights-tidy-up.md" in result.output
    assert f"Wrote the story's scorecard to {card}" in result.output
    page = card.read_text(encoding="utf-8")
    assert "Hold: 9 cases got worse beyond noise" in page
    assert "honor the 20% discount" in page


def test_a_verdict_missing_from_the_recording_is_refused_offline_and_never_bought(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = tmp_path / "recordings"
    stale.mkdir()
    shutil.copy(demo.RECORDINGS / "baseline.jsonl", stale)
    lines = (demo.RECORDINGS / "dwights-tidy-up.jsonl").read_text(encoding="utf-8").splitlines()
    first_verdict = next(n for n, line in enumerate(lines) if '"check":null' not in line)
    del lines[first_verdict]
    (stale / "dwights-tidy-up.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(demo, "RECORDINGS", stale)

    story = asyncio.run(demo.replay(tmp_path / "runs"))

    assert story.candidate.without_verdict == 1
    assert story.candidate.manifest.spent_usd == 0.0
    assert not story.candidate.manifest.charges
    [unsure] = [
        grade
        for result in story.candidate.results
        for grade in result.grades
        if grade.passed is None
    ]
    assert unsure.reason.startswith("no verdict: no recorded verdict for check")


def test_answers_recorded_for_one_prompt_are_refused_for_the_other(tmp_path: Path) -> None:
    async def mismatched() -> Run:
        suite = load_suite(demo.SUITE)
        return await demo._replay(  # noqa: SLF001  (the story's own replay, given the wrong prompt)
            suite, demo.RECORDINGS / "baseline.jsonl", tmp_path, system=demo.TIDY_UP
        )

    replayed = asyncio.run(mismatched())

    assert replayed.results == ()
    assert len(replayed.failures) == 200
    assert {failure.kind for failure in replayed.failures} == {"provider"}
    assert "was made for a different prompt" in replayed.failures[0].reason
    assert replayed.manifest.spent_usd == 0.0
