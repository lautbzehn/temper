from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from temper.doctor import examine
from temper.errors import ProviderError
from tests.support import judged, make_suite, mock_client

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_the_checks_come_in_the_order_a_person_would_fix_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)

    diagnoses = asyncio.run(examine(None, tmp_path / "runs"))

    assert [diagnosis.name for diagnosis in diagnoses] == [
        "Python",
        "Temper",
        "Credentials",
        "Model claude-sonnet-5-5",
        "Model claude-opus-5-5",
        "Runs folder",
        "Offline run",
    ]
    assert all(diagnosis.ok for diagnosis in diagnoses)
    assert (tmp_path / "runs").exists() is False
    assert "would be made" in diagnoses[-2].note


def test_a_suite_names_the_models_to_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)
    suite = make_suite(judged("a"), judge={"model": "claude-opus-5-5"})

    diagnoses = asyncio.run(examine(suite, tmp_path))

    assert [diagnosis.name for diagnosis in diagnoses if diagnosis.name.startswith("Model")] == [
        "Model claude-opus-5-5"
    ]


def test_an_old_python_and_a_folder_that_cannot_be_written_are_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)
    monkeypatch.setattr("temper.doctor.platform.python_version", lambda: "3.9.1")
    blocked = tmp_path / "file"
    blocked.write_text("not a folder", encoding="utf-8")

    diagnoses = {diagnosis.name: diagnosis for diagnosis in asyncio.run(examine(None, blocked))}

    assert not diagnoses["Python"].ok
    assert diagnoses["Python"].note == "3.9.1; Temper needs 3.11 or newer"
    assert not diagnoses["Runs folder"].ok
    assert "can't write in" in diagnoses["Runs folder"].note
    assert diagnoses["Offline run"].ok


def test_a_scripted_run_that_does_not_finish_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("temper.providers.claude.AsyncAnthropic", mock_client)

    async def broken(*_: object, **__: object) -> None:
        raise ProviderError("the script is missing a reply")

    monkeypatch.setattr("temper.doctor.run_suite", broken)

    diagnoses = {diagnosis.name: diagnosis for diagnosis in asyncio.run(examine(None, tmp_path))}

    assert not diagnoses["Offline run"].ok
    assert diagnoses["Offline run"].note == (
        "a scripted run didn't finish: the script is missing a reply"
    )
