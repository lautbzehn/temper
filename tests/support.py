"""Helpers the tests share: files written on the fly, small suites, and test providers."""

from __future__ import annotations

import asyncio
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from temper.providers import Completion, Request
from temper.suite import Suite

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


def make_suite(*cases: dict[str, Any], trials: int = 1, name: str = "test") -> Suite:
    """A suite with a fake target and the given cases."""
    return Suite.model_validate(
        {
            "schema": 1,
            "name": name,
            "target": {"provider": "fake", "model": "fake-1"},
            "trials": trials,
            "cases": list(cases),
        }
    )


@dataclass
class Slow:
    """A provider that holds each request for a moment and counts how many it holds at once.

    Each request waits less than the one before it, so answers finish in the
    reverse of the order they were asked.
    """

    answer: str = "yes"
    started: int = 0
    in_flight: int = 0
    most_in_flight: int = 0
    seen: list[tuple[str, int]] = field(default_factory=list)

    async def complete(self, request: Request) -> Completion:
        self.started += 1
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        await asyncio.sleep(0.04 / self.started)
        self.seen.append((request.case_id, request.trial))
        self.in_flight -= 1
        return Completion(text=self.answer, model="slow")
