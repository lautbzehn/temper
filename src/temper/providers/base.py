"""What every provider shares: the request, the completion, and what answering used.

A provider is anything with an async `complete`. The fake one answers from a
script, the replay one from a recording, and the Claude one from the API.
"""

from __future__ import annotations

import hashlib
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from temper.suite import Message

Status = Literal["complete", "truncated", "refused"]


class Usage(BaseModel):
    """The tokens one answer used, as the API counted them."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class Request(BaseModel):
    """What a provider is asked for one trial of one case."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    trial: int
    model: str | None
    system: str | None
    messages: tuple[Message, ...]
    max_tokens: int
    options: dict[str, JsonValue] = Field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """A short hash of everything the model is sent, so a recording can tell when it changed."""
        sent = self.model_dump_json(exclude={"case_id", "trial"})
        return hashlib.sha256(sent.encode()).hexdigest()[:16]


class Completion(BaseModel):
    """An answer: its text, who gave it, whether it was cut short or refused, and its usage."""

    model_config = ConfigDict(frozen=True)

    text: str
    model: str
    status: Status = "complete"
    usage: Usage = Field(default_factory=Usage)
    request_id: str | None = None


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
