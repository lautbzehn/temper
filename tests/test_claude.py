from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from temper.errors import ProviderError, TransientError
from temper.providers import ClaudeProvider, ClaudeSettings, Completion, Request
from temper.suite import Message

Handler = Callable[[httpx2.Request], httpx2.Response]


def message(
    text: str = "Hello Bob",
    *,
    stop_reason: str = "end_turn",
    model: str = "claude-sonnet-5-5",
    **extra: Any,
) -> dict[str, Any]:
    """The API's JSON for one answer."""
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}] if text else [],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 12,
            "output_tokens": 3,
            "cache_read_input_tokens": 4,
            "cache_creation_input_tokens": 5,
        },
        **extra,
    }


def api_error(status: int, kind: str, text: str, **headers: str) -> httpx2.Response:
    body = {"type": "error", "error": {"type": kind, "message": text}}
    return httpx2.Response(status, headers=headers, json=body)


class Api:
    """A stand-in for the Anthropic API that answers from a handler and remembers what was sent."""

    def __init__(self, handler: Handler) -> None:
        self.sent: list[dict[str, Any]] = []
        self._handler = handler

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(json.loads(request.content))
        return self._handler(request)

    def provider(self, **settings: Any) -> ClaudeProvider:
        client = AsyncAnthropic(
            api_key="sk-ant-test",
            max_retries=0,
            http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(self)),
        )
        return ClaudeProvider(client, ClaudeSettings(**settings))


def request(system: str | None = "Be brief.") -> Request:
    return Request(
        case_id="order-status",
        trial=1,
        model="claude-sonnet-5-5",
        system=system,
        messages=(
            Message(role="user", content="Hi"),
            Message(role="assistant", content="Hello"),
            Message(role="user", content="Where is order 4471?"),
        ),
        max_tokens=64,
    )


def complete(api: Api, req: Request | None = None, **settings: Any) -> Completion:
    return asyncio.run(api.provider(**settings).complete(req or request()))


def test_an_answer_carries_its_text_model_usage_and_request_id() -> None:
    api = Api(lambda _: httpx2.Response(200, headers={"request-id": "req_1"}, json=message()))

    completion = complete(api)

    assert (completion.text, completion.model, completion.status) == (
        "Hello Bob",
        "claude-sonnet-5-5",
        "complete",
    )
    assert completion.usage.model_dump() == {
        "input_tokens": 12,
        "output_tokens": 3,
        "cache_read_tokens": 4,
        "cache_write_tokens": 5,
    }
    assert completion.request_id == "req_1"


def test_the_request_sends_the_system_prompt_the_turns_and_the_cap() -> None:
    api = Api(lambda _: httpx2.Response(200, json=message()))

    complete(api, effort="low")

    [sent] = api.sent
    assert sent["model"] == "claude-sonnet-5-5"
    assert sent["max_tokens"] == 64
    assert sent["system"] == "Be brief."
    assert [turn["role"] for turn in sent["messages"]] == ["user", "assistant", "user"]
    assert sent["output_config"] == {"effort": "low"}
    assert "fallbacks" not in sent


def test_no_system_prompt_and_no_effort_are_left_out_of_the_request() -> None:
    api = Api(lambda _: httpx2.Response(200, json=message()))

    complete(api, request(system=None))

    [sent] = api.sent
    assert "system" not in sent
    assert "output_config" not in sent


@pytest.mark.parametrize(
    ("stop_reason", "status"),
    [
        ("end_turn", "complete"),
        ("stop_sequence", "complete"),
        ("max_tokens", "truncated"),
        ("model_context_window_exceeded", "truncated"),
        ("refusal", "refused"),
    ],
)
def test_the_stop_reason_becomes_a_status(stop_reason: str, status: str) -> None:
    api = Api(lambda _: httpx2.Response(200, json=message("", stop_reason=stop_reason)))

    assert complete(api).status == status


def test_a_stop_reason_temper_does_not_handle_is_an_error() -> None:
    api = Api(lambda _: httpx2.Response(200, json=message(stop_reason="tool_use")))

    with pytest.raises(
        ProviderError, match="stopped for a reason Temper doesn't handle: 'tool_use'"
    ):
        complete(api)


def test_a_rate_limit_is_transient_and_passes_on_the_wait_the_api_asked_for() -> None:
    api = Api(lambda _: api_error(429, "rate_limit_error", "slow down", **{"retry-after": "7"}))

    with pytest.raises(TransientError, match="rate limited: slow down") as caught:
        complete(api)

    assert caught.value.retry_after == 7.0


def test_a_rate_limit_without_a_usable_wait_passes_none() -> None:
    api = Api(
        lambda _: api_error(429, "rate_limit_error", "slow down", **{"retry-after": "Thu, 01 Jan"})
    )

    with pytest.raises(TransientError) as caught:
        complete(api)

    assert caught.value.retry_after is None


def test_an_outage_passes_on_the_wait_the_api_asked_for() -> None:
    api = Api(lambda _: api_error(529, "overloaded_error", "busy", **{"retry-after": "12"}))

    with pytest.raises(TransientError) as caught:
        complete(api)

    assert caught.value.retry_after == 12.0


def test_an_answer_that_is_not_a_message_is_an_error_not_a_crash() -> None:
    api = Api(lambda _: httpx2.Response(200, json={"unexpected": True}))

    with pytest.raises(ProviderError, match="wasn't a message Temper can read"):
        complete(api)


@pytest.mark.parametrize("status", [408, 409, 500, 529])
def test_an_outage_is_transient(status: int) -> None:
    api = Api(lambda _: api_error(status, "overloaded_error", "busy"))

    with pytest.raises(TransientError, match=rf"couldn't answer \({status}\): busy"):
        complete(api)


def test_a_rejected_request_is_final() -> None:
    api = Api(lambda _: api_error(400, "invalid_request_error", "max_tokens is too large"))

    with pytest.raises(
        ProviderError, match=r"refused the request \(400\): max_tokens is too large"
    ):
        complete(api)


def test_an_error_without_a_json_body_keeps_the_body_as_its_message() -> None:
    api = Api(lambda _: httpx2.Response(502, text="Bad gateway"))

    with pytest.raises(TransientError, match=r"couldn't answer \(502\): Bad gateway"):
        complete(api)


def test_an_error_whose_message_is_not_text_keeps_the_sdk_wording() -> None:
    body = {"type": "error", "error": {"type": "api_error", "message": 42}}
    api = Api(lambda _: httpx2.Response(500, json=body))

    with pytest.raises(TransientError, match=r"couldn't answer \(500\): Error code: 500"):
        complete(api)


def test_rejected_credentials_are_final_and_say_so() -> None:
    api = Api(lambda _: api_error(401, "authentication_error", "invalid x-api-key"))

    with pytest.raises(ProviderError, match="rejected the credentials: invalid x-api-key"):
        complete(api)


def test_network_trouble_and_timeouts_are_transient() -> None:
    def unreachable(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=req)

    def slow(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("too slow", request=req)

    with pytest.raises(TransientError, match="couldn't reach the API"):
        complete(Api(unreachable))
    with pytest.raises(TransientError, match="couldn't reach the API"):
        complete(Api(slow))


def test_a_request_without_a_model_is_an_error() -> None:
    api = Api(lambda _: httpx2.Response(200, json=message()))
    req = request().model_copy(update={"model": None})

    with pytest.raises(ProviderError, match=r"needs target\.model"):
        complete(api, req)


def test_estimate_counts_tokens_through_the_api() -> None:
    api = Api(lambda _: httpx2.Response(200, json={"input_tokens": 42}))

    assert asyncio.run(api.provider().estimate(request())) == 42
    assert api.sent[0]["system"] == "Be brief."


def test_closing_twice_is_fine() -> None:
    provider = Api(lambda _: httpx2.Response(200, json=message())).provider()

    asyncio.run(provider.aclose())
    asyncio.run(provider.aclose())


def test_an_estimate_that_fails_is_an_error() -> None:
    api = Api(lambda _: api_error(400, "invalid_request_error", "no such model"))

    with pytest.raises(ProviderError, match="couldn't count tokens"):
        asyncio.run(api.provider().estimate(request()))
