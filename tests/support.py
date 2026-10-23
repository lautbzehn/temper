"""Helpers the tests share: files written on the fly, small suites, and obedient providers."""

from __future__ import annotations

import asyncio
import json
import textwrap
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx2
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from temper.graders import Answer
from temper.planning import Estimates, Plan, Providers
from temper.providers import Completion, Request, Usage
from temper.results import RunOptions
from temper.runner import run_suite
from temper.suite import Message, Suite

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from temper.providers import Provider, Status
    from temper.results import Run

EXAMPLE = Path(__file__).parents[1] / "examples" / "dunder-mifflin" / "suite.yaml"


@dataclass(frozen=True)
class Files:
    """Writes files into one temporary folder, dedenting the text first."""

    root: Path

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
        return path


def case(case_id: str, *checks: dict[str, Any]) -> dict[str, Any]:
    """A case as a suite file would spell it, checking for "yes" unless told otherwise."""
    return {
        "id": case_id,
        "input": f"A question for {case_id}",
        "checks": list(checks) or [{"type": "contains", "text": "yes"}],
    }


def make_suite(
    *cases: dict[str, Any],
    trials: int = 1,
    name: str = "test",
    model: str | None = "fake-1",
    options: dict[str, Any] | None = None,
    judge: dict[str, Any] | None = None,
) -> Suite:
    """A suite with a fake target and the given cases, judged by `judge-1` unless told otherwise."""
    return Suite.model_validate(
        {
            "schema": 1,
            "name": name,
            "target": {"provider": "fake", "model": model, "options": options or {}},
            "judge": judge or {"model": "judge-1"},
            "trials": trials,
            "cases": list(cases),
        }
    )


def judged(case_id: str, property_: str = "is polite") -> dict[str, Any]:
    """A case with one judge check."""
    return case(case_id, {"type": "judge", "property": property_})


def answer(
    text: str = "yes",
    *,
    model: str = "fake-1",
    status: Status = "complete",
    usage: Usage | None = None,
) -> Completion:
    """A completion with sensible defaults."""
    return Completion(text=text, model=model, status=status, usage=usage or Usage())


def seen(text: str, *, latency_ms: float = 100.0, cost_usd: float | None = 0.001) -> Answer:
    """An answer as a grader sees it."""
    conversation = (Message(role="user", content="A question"),)
    return Answer(text=text, conversation=conversation, latency_ms=latency_ms, cost_usd=cost_usd)


def verdict(
    *, passed: bool, reason: str = "because", model: str = "judge-1", usage: Usage | None = None
) -> Completion:
    """A judge's completion: a verdict as JSON."""
    text = json.dumps({"reason": reason, "passed": passed})
    return Completion(text=text, model=model, usage=usage or Usage())


def providers(answers: Provider | Providers, judge: Provider | None = None) -> Providers:
    """The providers as given, or a bare provider wrapped as the one that answers."""
    if isinstance(answers, Providers):
        return answers
    return Providers(answers, judge)


def plan(
    suite: Suite,
    answers: Provider | Providers,
    judge: Provider | None = None,
    options: RunOptions | None = None,
) -> Plan:
    """A plan with nothing counted and no budget held."""
    return Plan(suite, providers(answers, judge), options or RunOptions(), Estimates(), None)


def run(
    suite: Suite,
    answers: Provider | Providers,
    out: Path,
    options: RunOptions | None = None,
    *,
    judge: Provider | None = None,
) -> Run:
    """Run a suite to completion under `out`."""
    chosen = providers(answers, judge)
    return asyncio.run(run_suite(suite, chosen, out=out, options=options))


@dataclass
class Scripted:
    """A provider that answers each case from a script, in order: a completion or an error."""

    script: Mapping[str, Sequence[Completion | Exception]]
    tokens: dict[str, int] = field(default_factory=dict)
    charges: bool = False
    calls: list[tuple[str, int]] = field(default_factory=list)
    requests: list[Request] = field(default_factory=list)
    estimated: list[Request] = field(default_factory=list)
    queues: dict[str, list[Completion | Exception]] = field(init=False)

    def __post_init__(self) -> None:
        self.queues = {case_id: list(outcomes) for case_id, outcomes in self.script.items()}

    async def complete(self, request: Request, /) -> Completion:
        self.calls.append((request.case_id, request.trial))
        self.requests.append(request)
        outcome = self.queues[request.case_id].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def estimate(self, request: Request, /) -> int:
        self.estimated.append(request)
        return self.tokens.get(request.case_id, 0)

    async def aclose(self) -> None:
        pass


@dataclass
class Stuck:
    """A provider that never answers; `asked` is set once a request is waiting on it."""

    charges: bool = True
    tokens: int = 1_000
    asked: asyncio.Event = field(default_factory=asyncio.Event)

    async def complete(self, _request: Request, /) -> Completion:
        self.asked.set()
        await asyncio.Event().wait()
        raise AssertionError("never answers")

    async def estimate(self, _request: Request, /) -> int:
        return self.tokens

    async def aclose(self) -> None:
        pass


@dataclass
class Slow:
    """A provider that holds each request for a moment and counts how many it holds at once.

    Each request waits less than the one before it, so answers finish in the
    reverse of the order they were asked.
    """

    text: str = "yes"
    charges: bool = False
    started: int = 0
    in_flight: int = 0
    most_in_flight: int = 0
    seen: list[tuple[str, int]] = field(default_factory=list)

    async def complete(self, request: Request, /) -> Completion:
        self.started += 1
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        await asyncio.sleep(0.04 / self.started)
        self.seen.append((request.case_id, request.trial))
        self.in_flight -= 1
        return Completion(text=self.text, model=request.model or "slow")

    async def estimate(self, _request: Request, /) -> int:
        return 0

    async def aclose(self) -> None:
        pass


class _ApiHandler(BaseHTTPRequestHandler):
    """Answers like the Anthropic API would, over real keep-alive connections."""

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body: dict[str, object]
        if self.path.endswith("/count_tokens"):
            body = {"input_tokens": 10}
        else:
            body = {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": "Hello!"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_: object) -> None:
        """Keep the test output clean."""


@contextmanager
def local_api() -> Iterator[str]:
    """A stand-in for the Anthropic API on a real local socket; yields its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def mock_client(**settings: Any) -> AsyncAnthropic:
    """A client for a pretend API: it greets, or gives a passing verdict when asked for JSON."""

    def api(request: httpx2.Request) -> httpx2.Response:
        asked = json.loads(request.content)
        if request.url.path.endswith("count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 10})
        shaped = "format" in asked.get("output_config", {})
        text = '{"reason": "It greets.", "passed": true}' if shaped else "Hello!"
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": asked["model"],
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    transport = httpx2.MockTransport(api)
    return AsyncAnthropic(**settings, http_client=DefaultAsyncHttpxClient(transport=transport))
