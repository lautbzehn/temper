from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from temper.errors import ProviderError, UnknownNameError
from temper.providers import FakeProvider, Request, build_provider
from temper.suite import Message, Target

if TYPE_CHECKING:
    from tests.support import Files


def ask(provider: FakeProvider, case_id: str, trial: int) -> str:
    request = Request(
        case_id=case_id,
        trial=trial,
        model=None,
        system=None,
        messages=(Message(role="user", content="Hi"),),
        max_tokens=100,
    )
    return asyncio.run(provider.complete(request)).text


def test_replies_take_turns_by_trial() -> None:
    provider = FakeProvider({"wobbly": ["first", "second", "third"]})

    assert [ask(provider, "wobbly", trial) for trial in range(1, 5)] == [
        "first",
        "second",
        "third",
        "first",
    ]


def test_a_case_without_a_reply_is_an_error() -> None:
    with pytest.raises(ProviderError, match="no fake reply for case 'ghost'"):
        ask(FakeProvider({}), "ghost", 1)


def test_replies_load_from_a_file_with_one_or_many_per_case(files: Files) -> None:
    path = files.write("replies.yaml", "steady: Always this\nwobbly: [one, two]\n")
    provider = FakeProvider.from_file(path)

    assert ask(provider, "steady", 2) == "Always this"
    assert ask(provider, "wobbly", 2) == "two"


def test_a_replies_file_of_the_wrong_shape_is_an_error(files: Files) -> None:
    path = files.write("replies.yaml", "- not\n- a mapping\n")

    with pytest.raises(ProviderError, match="must map each case id"):
        FakeProvider.from_file(path)


def test_a_missing_replies_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ProviderError, match="can't read fake replies"):
        FakeProvider.from_file(tmp_path / "gone.yaml")


def test_build_provider_reads_options_relative_to_the_suite(files: Files) -> None:
    files.write("replies.yaml", "case: hello\n")
    target = Target(provider="fake", options={"replies": "replies.yaml"})

    provider = build_provider(target, files.root)

    assert isinstance(provider, FakeProvider)


def test_build_provider_checks_the_options() -> None:
    with pytest.raises(ValidationError):
        build_provider(Target(provider="fake", options={}), Path())


def test_build_provider_rejects_unknown_names() -> None:
    with pytest.raises(UnknownNameError, match=r"unknown provider 'fakes'; did you mean 'fake'\?"):
        build_provider(Target(provider="fakes"), Path())
