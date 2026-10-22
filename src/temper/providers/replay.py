"""The replay provider: answers recorded from a real run, played back with no network and no cost.

Every live run writes a `recording.jsonl` beside its results. A replay points
at one of those files and refuses to answer a case whose prompt has changed
since, so a replayed score always describes the prompt that was actually run.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, ValidationError

from temper.errors import ProviderError, UnreadableFileError
from temper.files import read_text
from temper.providers.base import Completion, Request
from temper.suite import Closed

if TYPE_CHECKING:
    from collections.abc import Mapping

    from temper.suite import Target


class ReplaySettings(Closed):
    """Options for the replay provider: the recording to play back."""

    recording: Path


class Recording(BaseModel):
    """One recorded answer: which trial, a fingerprint of what was sent, and the completion."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    trial: int
    fingerprint: str
    completion: Completion

    @classmethod
    def of(cls, request: Request, completion: Completion) -> Self:
        """The recording of one answered request."""
        return cls(
            case_id=request.case_id,
            trial=request.trial,
            fingerprint=request.fingerprint,
            completion=completion,
        )


Slot = tuple[str, int]


class ReplayProvider:
    """Answers each (case, trial) with what was recorded for it."""

    charges = False

    def __init__(self, recordings: Mapping[Slot, Recording]) -> None:
        self._recordings = recordings

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Read a `recording.jsonl` file, one recorded answer per line.

        Raises:
            ProviderError: the file can't be read, a line isn't a recorded answer,
                or one trial is recorded twice.
        """
        try:
            lines = read_text(path).splitlines()
        except UnreadableFileError as error:
            raise ProviderError(f"can't read recording {str(path)!r}: {error.reason}") from None

        recordings: dict[Slot, Recording] = {}
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                recording = Recording.model_validate_json(line)
            except ValidationError:
                raise ProviderError(
                    f"line {number} of recording {str(path)!r} isn't a recorded answer"
                ) from None
            slot = (recording.case_id, recording.trial)
            if slot in recordings:
                raise ProviderError(
                    f"recording {str(path)!r} answers case {slot[0]!r} trial {slot[1]} twice"
                )
            recordings[slot] = recording
        return cls(recordings)

    async def complete(self, request: Request, /) -> Completion:
        """The recorded answer for this trial, if it was recorded for the same prompt."""
        recording = self._find(request)
        if recording is None:
            raise ProviderError(
                f"no recorded answer for case {request.case_id!r} trial {request.trial}; "
                "run the suite live once to record one"
            )
        if recording.fingerprint != request.fingerprint:
            raise ProviderError(
                f"the recorded answer for case {request.case_id!r} trial {request.trial} "
                "was made for a different prompt, model, options, or max_tokens; "
                "run the suite live again to record it"
            )
        return recording.completion

    async def estimate(self, request: Request, /) -> int:
        """The recorded answer's input tokens, or none when nothing was recorded."""
        recording = self._find(request)
        return recording.completion.usage.input_tokens if recording else 0

    async def aclose(self) -> None:
        """Nothing is held open."""

    def _find(self, request: Request) -> Recording | None:
        return self._recordings.get((request.case_id, request.trial))


def build(target: Target, base_dir: Path) -> ReplayProvider:
    """A replay provider from a suite's target, its recording read relative to `base_dir`."""
    settings = ReplaySettings.model_validate(target.options)
    return ReplayProvider.from_file(base_dir / settings.recording)
