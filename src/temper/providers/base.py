"""What every provider shares: the request, the completion, and what answering used.

A provider is anything with an async `complete`. The fake one answers from a
script, the replay one from a recording, and the Claude one from the API. A
request is usually one trial of one case; the judge's question about one of
its checks is a request too, and goes through the same provider.
"""

from __future__ import annotations

import hashlib
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from temper.suite import Message

Status = Literal["complete", "truncated", "refused"]

# One trial of one case.
Slot = tuple[str, int]


class Usage(BaseModel):
    """The tokens one answer used, as the API counted them."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class Request(BaseModel):
    """What a provider is asked: a trial's answer, or the judge's verdict on one of its checks."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    trial: int
    check: int | None = None
    model: str | None
    system: str | None
    messages: tuple[Message, ...]
    max_tokens: int
    options: dict[str, JsonValue] = Field(default_factory=dict)
    json_schema: dict[str, JsonValue] | None = None

    @property
    def key(self) -> tuple[str, int, int | None]:
        """What the request is for: the case, the trial, and the check when it's a verdict."""
        return (self.case_id, self.trial, self.check)

    @property
    def fingerprint(self) -> str:
        """A short hash of everything the model is sent, so a recording can tell when it changed."""
        sent = self.model_dump_json(exclude={"case_id", "trial", "check"})
        return hashlib.sha256(sent.encode()).hexdigest()[:16]


class Completion(BaseModel):
    """An answer: its text, who gave it, whether it was cut short or refused, and its usage.

    `latency_ms` is set only when the provider knows better than the caller's
    clock, as a replay does: it carries the time the recorded answer took.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    model: str
    status: Status = "complete"
    usage: Usage = Field(default_factory=Usage)
    request_id: str | None = None
    latency_ms: float | None = None


class Provider(Protocol):
    """Anything that can answer a request."""

    @property
    def charges(self) -> bool:
        """Whether each answer costs money."""
        ...

    async def complete(self, request: Request, /) -> Completion:
        """Answer one request.

        Raises:
            TransientError: it couldn't be answered just now; another try might work.
            ProviderError: it can't be answered, and trying again wouldn't help.
        """
        ...

    async def estimate(self, request: Request, /) -> int:
        """How many input tokens the request would use, as closely as the provider can tell."""
        ...

    async def aclose(self) -> None:
        """Let go of anything held open, such as connections. Safe to call more than once."""
        ...


def served_matches(requested: str | None, served: str) -> bool:
    """Whether the model that answered is the one asked for, allowing a dated snapshot of it."""
    return requested is None or served == requested or served.startswith(f"{requested}-")


def same_model(one: str, other: str) -> bool:
    """Whether two names are one model, either being a dated snapshot of the other."""
    return served_matches(one, other) or served_matches(other, one)
