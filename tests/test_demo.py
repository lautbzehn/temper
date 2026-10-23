from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from temper import demo
from temper.cli import app

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
