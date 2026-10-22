"""Providers answer the cases.

M0 ships the fake provider, which answers from a script so a suite runs
offline with the same answers every time. Real models arrive in M1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final, Protocol, Self

import yaml
from pydantic import BeforeValidator, Field, TypeAdapter, ValidationError

from temper.errors import ProviderError, UnknownNameError, UnreadableFileError
from temper.files import read_text
from temper.suite import CaseId, Closed, Message

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from temper.suite import Target


@dataclass(frozen=True, slots=True, kw_only=True)
class Request:
    """What a provider is asked for one trial of one case."""

    case_id: str
    trial: int
    model: str | None
    system: str | None
    messages: tuple[Message, ...]
    max_tokens: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Completion:
    """A provider's answer, and the model that gave it."""

    text: str
    model: str


class Provider(Protocol):
    """Anything that can answer a request."""

    async def complete(self, request: Request) -> Completion:
        """Answer one request."""
        ...


class FakeSettings(Closed):
    """Options for the fake provider: the file that holds its scripted replies."""

    replies: Path


def _as_list(value: object) -> object:
    return [value] if isinstance(value, str) else value


# One reply, or a list of at least one, for each case id.
_Replies = Annotated[list[str], BeforeValidator(_as_list), Field(min_length=1)]
_REPLIES = TypeAdapter(dict[CaseId, _Replies])


class FakeProvider:
    """Answers from scripted replies, one or more per case.

    Trial 1 gets a case's first reply, trial 2 the next, and the list repeats,
    so a short script can stand in for a model that isn't always consistent.
    """

    def __init__(self, replies: Mapping[str, list[str]]) -> None:
        self._replies = replies

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Read scripted replies from a YAML file that maps case ids to a reply or a list of them.

        Raises:
            ProviderError: the file can't be read or doesn't have that shape.
        """
        try:
            return cls(_REPLIES.validate_python(yaml.safe_load(read_text(path))))
        except UnreadableFileError as error:
            raise ProviderError(f"can't read fake replies {str(path)!r}: {error.reason}") from None
        except (yaml.YAMLError, ValidationError):
            raise ProviderError(
                f"fake replies in {str(path)!r} must map each case id to a reply or a list of them"
            ) from None

    async def complete(self, request: Request) -> Completion:
        """Answer with the scripted reply for this case and trial."""
        replies = self._replies.get(request.case_id)
        if not replies:
            raise ProviderError(f"no fake reply for case {request.case_id!r}")
        return Completion(text=replies[(request.trial - 1) % len(replies)], model="fake")


def _fake(target: Target, base_dir: Path) -> FakeProvider:
    settings = FakeSettings.model_validate(target.options)
    return FakeProvider.from_file(base_dir / settings.replies)


PROVIDERS: Final[Mapping[str, Callable[[Target, Path], Provider]]] = {"fake": _fake}


def build_provider(target: Target, base_dir: Path) -> Provider:
    """The provider a suite's target names, set up from its options.

    Paths in the options are read relative to `base_dir`, usually `suite.folder`.

    Raises:
        UnknownNameError: no provider has that name.
        pydantic.ValidationError: the options don't fit that provider.
        ProviderError: the provider couldn't be set up.
    """
    build = PROVIDERS.get(target.provider)
    if build is None:
        raise UnknownNameError("provider", target.provider, PROVIDERS)
    return build(target, base_dir)
