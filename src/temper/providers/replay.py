"""The replay provider: answers from a recording, so a run costs nothing and needs no network.

A recording is only honest while it describes what would actually be sent, so
a request whose prompt, model, options, or shape has changed since is refused
rather than answered with a stale completion.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict

from temper import jsonl
from temper.errors import BadLineError, ProviderError, UnreadableFileError
from temper.providers.base import Completion, Request
from temper.suite import Closed

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from temper.suite import Target

# What a recording is of: the case, the trial, and the check when it holds a verdict.
Key = tuple[str, int, int | None]


class ReplaySettings(Closed):
    """Options for the replay provider: the recording to answer from."""

    recording: Path


class Recording(BaseModel):
    """One completion as it came back, and a fingerprint of the request that got it."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    trial: int
    check: int | None = None
    fingerprint: str
    completion: Completion

    @classmethod
    def of(cls, request: Request, completion: Completion) -> Self:
        """The recording of `completion` answering `request`."""
        return cls(
            case_id=request.case_id,
            trial=request.trial,
            check=request.check,
            fingerprint=request.fingerprint,
            completion=completion,
        )

    @property
    def key(self) -> Key:
        """What the recording is of."""
        return (self.case_id, self.trial, self.check)


class ReplayProvider:
    """Answers each request with what the same request got when it was recorded."""

    charges = False

    def __init__(self, recordings: Iterable[Recording]) -> None:
        self._recorded: Mapping[Key, Recording] = {record.key: record for record in recordings}

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Read a `recording.jsonl`, refusing one that records the same request twice.

        Raises:
            ProviderError: the file can't be read, or isn't a recording.
        """
        try:
            recordings = list(jsonl.read(path, Recording))
        except UnreadableFileError as error:
            raise ProviderError(f"can't read recording {str(path)!r}: {error.reason}") from None
        except BadLineError as error:
            raise ProviderError(
                f"line {error.line} of recording {str(path)!r} isn't a recorded answer"
            ) from None
        seen: set[Key] = set()
        for record in recordings:
            if record.key in seen:
                what, where = _describe(record.key)
                raise ProviderError(f"{str(path)!r} {what}s {where} twice")
            seen.add(record.key)
        return cls(recordings)

    def recorded(self, request: Request, /) -> Completion | None:
        """The completion recorded for this very request, if there is one."""
        record = self._recorded.get(request.key)
        if record is None or record.fingerprint != request.fingerprint:
            return None
        return record.completion

    def has(self, request: Request, /) -> bool:
        """Whether the recording holds an answer to this very request."""
        return self.recorded(request) is not None

    async def complete(self, request: Request, /) -> Completion:
        """The recorded completion, or a refusal when what's recorded isn't this request."""
        record = self._recorded.get(request.key)
        what, where = _describe(request.key)
        if record is None:
            raise ProviderError(f"no recorded {what} for {where}")
        if record.fingerprint != request.fingerprint:
            raise ProviderError(
                f"the recorded {what} for {where} was made for a different prompt, model, "
                "options, or max_tokens; run the suite live to record it again"
            )
        return record.completion

    async def estimate(self, request: Request, /) -> int:
        """The input tokens the recorded answer used, or none when nothing is recorded."""
        record = self._recorded.get(request.key)
        return record.completion.usage.input_tokens if record is not None else 0

    async def aclose(self) -> None:
        """Nothing is held open."""


def _describe(key: Key) -> tuple[str, str]:
    """What a key is for, as (what, where): `("answer", "case 'x' trial 2")`."""
    case_id, trial, check = key
    where = f"case {case_id!r} trial {trial}"
    return ("answer", where) if check is None else ("verdict", f"check {check} of {where}")


def build(target: Target, base_dir: Path) -> ReplayProvider:
    """A replay provider from a suite's target, its recording read relative to `base_dir`."""
    settings = ReplaySettings.model_validate(target.options)
    return ReplayProvider.from_file(base_dir / settings.recording)
