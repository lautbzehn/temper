"""The fake provider: scripted replies, so a suite runs offline with the same answers every time."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Self

import yaml
from pydantic import BeforeValidator, Field, TypeAdapter, ValidationError

from temper.errors import ProviderError, UnreadableFileError
from temper.files import read_text
from temper.providers.base import Completion, Request
from temper.suite import CaseId, Closed

if TYPE_CHECKING:
    from collections.abc import Mapping

    from temper.suite import Target


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

    charges = False

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

    async def complete(self, request: Request, /) -> Completion:
        """The scripted reply for this case and trial, credited to whatever model was asked for."""
        replies = self._replies.get(request.case_id)
        if not replies:
            raise ProviderError(f"no fake reply for case {request.case_id!r}")
        text = replies[(request.trial - 1) % len(replies)]
        return Completion(text=text, model=request.model or "fake")

    async def estimate(self, _request: Request, /) -> int:
        """Scripted replies are free."""
        return 0


def build(target: Target, base_dir: Path) -> FakeProvider:
    """A fake provider from a suite's target, its replies file read relative to `base_dir`."""
    settings = FakeSettings.model_validate(target.options)
    return FakeProvider.from_file(base_dir / settings.replies)
