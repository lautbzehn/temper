from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from temper.cli import app

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).parents[1]


def test_the_judges_published_agreement_reproduces_from_the_shipped_pilot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(ROOT)

    result = CliRunner().invoke(app, ["calibrate", "examples/judge-pilot/run"])

    assert result.exit_code == 0, result.output
    assert "Agreement 97% (29 of 30) · kappa 0.65" in result.output
    assert "Trusted:" in result.output
