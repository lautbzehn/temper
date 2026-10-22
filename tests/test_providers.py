from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from temper.errors import ProviderError, UnknownNameError
from temper.providers import (
    ClaudeProvider,
    FakeProvider,
    Recording,
    ReplayProvider,
    Request,
    Usage,
    build_provider,
)
from temper.results import RunOptions
from temper.runner import provider_for
from temper.suite import Message, Target
from tests.support import answer, make_suite

if TYPE_CHECKING:
    from tests.support import Files


def request(case_id: str, trial: int, *, model: str | None = "fake-1", text: str = "Hi") -> Request:
    return Request(
        case_id=case_id,
        trial=trial,
        model=model,
        system=None,
        messages=(Message(role="user", content=text),),
        max_tokens=100,
    )


def ask(provider: FakeProvider | ReplayProvider, case_id: str, trial: int) -> str:
    return asyncio.run(provider.complete(request(case_id, trial))).text


def test_fake_replies_take_turns_by_trial() -> None:
    provider = FakeProvider({"wobbly": ["first", "second", "third"]})

    assert [ask(provider, "wobbly", trial) for trial in range(1, 5)] == [
        "first",
        "second",
        "third",
        "first",
    ]


def test_the_fake_answers_as_whatever_model_was_asked_for() -> None:
    provider = FakeProvider({"case": ["yes"]})

    assert asyncio.run(provider.complete(request("case", 1, model="claude-x"))).model == "claude-x"
    assert asyncio.run(provider.complete(request("case", 1, model=None))).model == "fake"


def test_a_case_without_a_fake_reply_is_an_error() -> None:
    with pytest.raises(ProviderError, match="no fake reply for case 'ghost'"):
        ask(FakeProvider({}), "ghost", 1)


def test_fake_replies_load_from_a_file_with_one_or_many_per_case(files: Files) -> None:
    path = files.write("replies.yaml", "steady: Always this\nwobbly: [one, two]\n")
    provider = FakeProvider.from_file(path)

    assert ask(provider, "steady", 2) == "Always this"
    assert ask(provider, "wobbly", 2) == "two"
    assert asyncio.run(provider.estimate(request("steady", 1))) == 0


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- not\n- a mapping\n", "must map each case id"),
        ("silent: []\n", "must map each case id"),
    ],
)
def test_a_fake_replies_file_of_the_wrong_shape_is_an_error(
    files: Files, text: str, message: str
) -> None:
    path = files.write("replies.yaml", text)

    with pytest.raises(ProviderError, match=message):
        FakeProvider.from_file(path)


def test_a_fake_replies_file_that_cannot_be_read_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "replies.yaml"
    path.write_bytes("case: Café\n".encode("latin-1"))

    with pytest.raises(ProviderError, match="it isn't UTF-8 text"):
        FakeProvider.from_file(path)
    with pytest.raises(ProviderError, match="can't read fake replies"):
        FakeProvider.from_file(tmp_path / "gone.yaml")


def recording_file(files: Files, *recordings: Recording, name: str = "recording.jsonl") -> Path:
    return files.write(name, "".join(r.model_dump_json() + "\n" for r in recordings) + "\n")


def test_a_replay_answers_each_trial_with_what_was_recorded(files: Files) -> None:
    first = Recording.of(
        request("case", 1), answer("one", model="claude-x", usage=Usage(input_tokens=7))
    )
    second = Recording.of(request("case", 2), answer("two", model="claude-x"))
    provider = ReplayProvider.from_file(recording_file(files, first, second))

    assert ask(provider, "case", 1) == "one"
    assert ask(provider, "case", 2) == "two"
    assert asyncio.run(provider.estimate(request("case", 1))) == 7
    assert asyncio.run(provider.estimate(request("case", 9))) == 0


def test_a_replay_refuses_a_trial_that_was_never_recorded(files: Files) -> None:
    provider = ReplayProvider.from_file(
        recording_file(files, Recording.of(request("case", 1), answer()))
    )

    with pytest.raises(ProviderError, match="no recorded answer for case 'case' trial 2"):
        ask(provider, "case", 2)


def test_a_replay_refuses_an_answer_recorded_for_a_different_prompt(files: Files) -> None:
    recorded = Recording.of(request("case", 1, text="Where is my order?"), answer())
    provider = ReplayProvider.from_file(recording_file(files, recorded))

    with pytest.raises(ProviderError, match="made for a different prompt, model, options, or max"):
        asyncio.run(provider.complete(request("case", 1, text="Where is my refund?")))


def test_a_replay_refuses_an_answer_recorded_with_different_options(files: Files) -> None:
    low = request("case", 1).model_copy(update={"options": {"effort": "low"}})
    high = request("case", 1).model_copy(update={"options": {"effort": "max"}})
    provider = ReplayProvider.from_file(recording_file(files, Recording.of(low, answer())))

    assert low.fingerprint != high.fingerprint
    with pytest.raises(ProviderError, match="different prompt, model, options, or max_tokens"):
        asyncio.run(provider.complete(high))


def test_a_recording_with_the_same_trial_twice_is_an_error(files: Files) -> None:
    recorded = Recording.of(request("case", 1), answer())
    path = recording_file(files, recorded, recorded)

    with pytest.raises(ProviderError, match="answers case 'case' trial 1 twice"):
        ReplayProvider.from_file(path)


def test_a_recording_with_a_bad_line_is_an_error(files: Files) -> None:
    path = files.write("recording.jsonl", json.dumps({"case_id": "x"}) + "\n")

    with pytest.raises(ProviderError, match=r"line 1 of recording .* isn't a recorded answer"):
        ReplayProvider.from_file(path)


def test_a_recording_that_cannot_be_read_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ProviderError, match="can't read recording"):
        ReplayProvider.from_file(tmp_path / "gone.jsonl")


def test_build_provider_reads_options_relative_to_the_suite(files: Files) -> None:
    files.write("replies.yaml", "case: hello\n")
    target = Target(provider="fake", options={"replies": "replies.yaml"})

    assert isinstance(build_provider(target, files.root), FakeProvider)


def test_build_provider_checks_the_options() -> None:
    with pytest.raises(ValidationError):
        build_provider(Target(provider="fake", options={}), Path())


def test_build_provider_rejects_unknown_names() -> None:
    with pytest.raises(UnknownNameError, match=r"unknown provider 'fakes'; did you mean 'fake'\?"):
        build_provider(Target(provider="fakes"), Path())


def test_the_claude_provider_needs_a_model() -> None:
    with pytest.raises(ProviderError, match=r"needs target\.model"):
        build_provider(Target(provider="claude"), Path())


def test_the_claude_provider_needs_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    provider = build_provider(Target(provider="claude", model="claude-sonnet-5-5"), Path())

    with pytest.raises(ProviderError, match="no Anthropic credentials found"):
        asyncio.run(provider.complete(request("case", 1, model="claude-sonnet-5-5")))
    with pytest.raises(ProviderError, match="no Anthropic credentials found"):
        asyncio.run(provider.estimate(request("case", 1, model="claude-sonnet-5-5")))


def test_the_claude_provider_builds_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    provider = build_provider(Target(provider="claude", model="claude-sonnet-5-5"), Path())

    assert isinstance(provider, ClaudeProvider)
    assert provider.charges


def test_provider_for_prefers_a_replay_when_the_options_name_one(files: Files) -> None:
    path = recording_file(files, Recording.of(request("case", 1), answer()))
    suite = make_suite(
        {"id": "case", "input": "Hi", "checks": [{"type": "contains", "text": "y"}]},
        options={"replies": "gone.yaml"},
    )

    assert isinstance(provider_for(suite, RunOptions(replay=path)), ReplayProvider)
    with pytest.raises(ProviderError, match="can't read fake replies"):
        provider_for(suite, RunOptions())
