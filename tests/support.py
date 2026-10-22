"""Helpers the tests share: files written on the fly, small suites, and obedient providers."""

from __future__ import annotations

import asyncio
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from temper.providers import Completion, Request, Usage
from temper.runner import run_suite
from temper.suite import Suite

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from temper.providers import Provider, Status
    from temper.results import Run, RunOptions

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
) -> Suite:
    """A suite with a fake target and the given cases."""
    return Suite.model_validate(
        {
            "schema": 1,
            "name": name,
            "target": {"provider": "fake", "model": model, "options": options or {}},
            "trials": trials,
            "cases": list(cases),
        }
    )


def answer(
    text: str = "yes",
    *,
    model: str = "fake-1",
    status: Status = "complete",
    usage: Usage | None = None,
) -> Completion:
    """A completion with sensible defaults."""
    return Completion(text=text, model=model, status=status, usage=usage or Usage())


def run(suite: Suite, provider: Provider, out: Path, options: RunOptions | None = None) -> Run:
    """Run a suite to completion under `out`."""
    return asyncio.run(run_suite(suite, provider, out=out, options=options))


@dataclass
class Scripted:
    """A provider that answers each case from a script, in order: a completion or an error."""

    script: Mapping[str, Sequence[Completion | Exception]]
    tokens: dict[str, int] = field(default_factory=dict)
    charges: bool = False
    calls: list[tuple[str, int]] = field(default_factory=list)
    queues: dict[str, list[Completion | Exception]] = field(init=False)

    def __post_init__(self) -> None:
        self.queues = {case_id: list(outcomes) for case_id, outcomes in self.script.items()}

    async def complete(self, request: Request, /) -> Completion:
        self.calls.append((request.case_id, request.trial))
        outcome = self.queues[request.case_id].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def estimate(self, request: Request, /) -> int:
        return self.tokens.get(request.case_id, 0)


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
