"""The Claude provider: answers from the Anthropic API, with the harness owning every retry.

The SDK's own retries are off and no fallback model is set, so each answer
comes from exactly the model that was asked, or the attempt fails and says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal, Self

import anthropic
from anthropic import AsyncAnthropic, omit
from pydantic import Field

from temper.errors import ProviderError, TransientError
from temper.providers.base import Completion, Request, Status, Usage
from temper.suite import Closed

if TYPE_CHECKING:
    from pathlib import Path

    from anthropic.types import Message as ApiMessage
    from anthropic.types import MessageParam
    from anthropic.types import Usage as ApiUsage

    from temper.suite import Message, Target

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class ClaudeSettings(Closed):
    """Options for the Claude provider: how hard it thinks, and how long one request may take."""

    effort: Effort | None = None
    timeout_s: Annotated[float, Field(gt=0)] = 60.0


# Status codes that mean "try again later", besides a rate limit's 429.
_SERVER_ERRORS = 500
_RETRY_LATER = frozenset({408, 409})

_NO_CREDENTIALS = (
    "no Anthropic credentials found; set ANTHROPIC_API_KEY or sign in with `ant auth login`"
)
_NEEDS_MODEL = "the claude provider needs target.model, for example claude-sonnet-5-5"


class ClaudeProvider:
    """Asks the model named in each request, through the Anthropic API.

    The client's connections belong to the event loop that first used them,
    so one provider serves one loop: plan, run, and close in the same one.
    """

    charges = True

    def __init__(self, client: AsyncAnthropic, settings: ClaudeSettings) -> None:
        self._client = client
        self._settings = settings

    @classmethod
    def from_settings(cls, settings: ClaudeSettings) -> Self:
        """A provider on a fresh client that reads its credentials from the environment."""
        return cls(AsyncAnthropic(max_retries=0, timeout=settings.timeout_s), settings)

    async def complete(self, request: Request, /) -> Completion:
        """Ask the model once. Rate limits, outages, and network trouble count as transient."""
        self._require_credentials()
        effort = self._settings.effort
        try:
            message = await self._client.messages.create(
                model=_model(request),
                max_tokens=request.max_tokens,
                system=request.system if request.system is not None else omit,
                messages=[_as_param(message) for message in request.messages],
                output_config={"effort": effort} if effort is not None else omit,
            )
        except anthropic.RateLimitError as error:
            raise TransientError(
                f"rate limited: {_said(error)}", retry_after=_retry_after(error)
            ) from error
        except anthropic.AuthenticationError as error:
            raise ProviderError(f"the API rejected the credentials: {_said(error)}") from error
        except anthropic.APIStatusError as error:
            if error.status_code in _RETRY_LATER or error.status_code >= _SERVER_ERRORS:
                raise TransientError(
                    f"the API couldn't answer ({error.status_code}): {_said(error)}",
                    retry_after=_retry_after(error),
                ) from error
            raise ProviderError(
                f"the API refused the request ({error.status_code}): {_said(error)}"
            ) from error
        except anthropic.APIConnectionError as error:
            raise TransientError(f"couldn't reach the API: {error}") from error
        try:
            return _completion(message)
        except (TypeError, AttributeError) as error:
            # The SDK is lenient about a 200 whose body isn't a message; Temper isn't.
            raise ProviderError("the API's answer wasn't a message Temper can read") from error

    async def estimate(self, request: Request, /) -> int:
        """Count the request's input tokens with the API, which costs nothing."""
        self._require_credentials()
        try:
            count = await self._client.messages.count_tokens(
                model=_model(request),
                system=request.system if request.system is not None else omit,
                messages=[_as_param(message) for message in request.messages],
            )
        except anthropic.APIError as error:
            raise ProviderError(f"couldn't count tokens: {error}") from error
        return count.input_tokens

    async def aclose(self) -> None:
        """Close the client's connections."""
        await self._client.close()

    def _require_credentials(self) -> None:
        """Refuse to call the API with no credentials.

        Checked on every call rather than when the provider is built, so a
        suite can be validated and replayed with no credentials at all.
        """
        client = self._client
        if client.api_key is None and client.auth_token is None and client.credentials is None:
            raise ProviderError(_NO_CREDENTIALS)


def _said(error: anthropic.APIStatusError) -> str:
    """What the API said, without the SDK's wrapping."""
    body = error.body
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        message = body["error"].get("message")
        if isinstance(message, str):
            return message
    return error.message


def _model(request: Request) -> str:
    if request.model is None:
        raise ProviderError(_NEEDS_MODEL)
    return request.model


def _as_param(message: Message) -> MessageParam:
    if message.role == "user":
        return {"role": "user", "content": message.content}
    return {"role": "assistant", "content": message.content}


def _retry_after(error: anthropic.APIStatusError) -> float | None:
    """How long the API asked us to wait, when it said so in seconds."""
    header = error.response.headers.get("retry-after")
    try:
        return float(header) if header is not None else None
    except ValueError:
        return None


def _completion(message: ApiMessage) -> Completion:
    text = "".join(block.text for block in message.content if block.type == "text")
    return Completion(
        text=text,
        model=message.model,
        status=_status(message),
        usage=_usage(message.usage),
        request_id=message._request_id,  # noqa: SLF001  (public by the SDK's own docs)
    )


def _status(message: ApiMessage) -> Status:
    match message.stop_reason:
        case "end_turn" | "stop_sequence":
            return "complete"
        case "max_tokens" | "model_context_window_exceeded":
            return "truncated"
        case "refusal":
            return "refused"
        case other:
            raise ProviderError(f"the API stopped for a reason Temper doesn't handle: {other!r}")


def _usage(usage: ApiUsage) -> Usage:
    return Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
    )


def build(target: Target, _base_dir: Path) -> ClaudeProvider:
    """A Claude provider from a suite's target."""
    if target.model is None:
        raise ProviderError(_NEEDS_MODEL)
    return ClaudeProvider.from_settings(ClaudeSettings.model_validate(target.options))
