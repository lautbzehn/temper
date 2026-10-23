"""A check-up that proves the wiring: Python, the package, credentials, the API, and a run.

Each diagnosis says what was found in words a person can act on. None
prints a secret, and none spends money: the API is only asked to count
tokens, which is free, and the trial run answers from a script.
"""

from __future__ import annotations

import asyncio
import platform
import tempfile
from contextlib import aclosing
from dataclasses import dataclass
from importlib.metadata import metadata
from pathlib import Path
from typing import TYPE_CHECKING

from temper import __version__
from temper.errors import ProviderError
from temper.planning import Providers
from temper.providers import ClaudeProvider, ClaudeSettings, FakeProvider, Request
from temper.runner import run_suite
from temper.suite import Message, Suite

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5")


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """One check's outcome: what was checked, whether it's fine, and what was found."""

    name: str
    ok: bool
    note: str


async def examine(suite: Suite | None, out: Path) -> list[Diagnosis]:
    """Run every check, in the order a person would fix them.

    With a suite, the models probed are the ones it names; a suite that
    names none needs no credentials, and none are asked for. Without a
    suite, Temper's default models are probed. A probe asks the API to
    count the tokens of one short request, which proves the credentials
    and the model name for free.
    """
    diagnoses = [_python(), _package()]
    models = _models(suite)
    if models:
        async with aclosing(ClaudeProvider.from_settings(ClaudeSettings())) as claude:
            diagnoses.append(_credentials(claude))
            diagnoses.extend(await asyncio.gather(*(_reachable(claude, model) for model in models)))
    else:
        note = "not needed: the suite names no Claude model"
        diagnoses.append(Diagnosis("Credentials", ok=True, note=note))
    diagnoses.append(_writable(out))
    diagnoses.append(await _offline_run())
    return diagnoses


def _python() -> Diagnosis:
    running = platform.python_version()
    least = metadata("temper-evals")["Requires-Python"].removeprefix(">=")
    fine = _parts(running) >= _parts(least)
    note = running if fine else f"{running}; Temper needs {least} or newer"
    return Diagnosis("Python", ok=fine, note=note)


def _parts(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split(".")[:2])


def _package() -> Diagnosis:
    return Diagnosis("Temper", ok=True, note=__version__)


def _credentials(claude: ClaudeProvider) -> Diagnosis:
    source = claude.credentials_source()
    if source is None:
        note = "none found; set ANTHROPIC_API_KEY or sign in with `ant auth login`"
        return Diagnosis("Credentials", ok=False, note=note)
    return Diagnosis("Credentials", ok=True, note=f"{source}, never shown here")


def _models(suite: Suite | None) -> Sequence[str]:
    """The Claude models the suite needs, or Temper's defaults when there's no suite to ask."""
    if suite is None:
        return DEFAULT_MODELS
    target = suite.target
    models = [target.model] if target.provider == "claude" and target.model else []
    if suite.judged:
        models.append(suite.judge.model)
    return models


async def _reachable(claude: ClaudeProvider, model: str) -> Diagnosis:
    asked = Request(
        case_id="doctor",
        trial=1,
        model=model,
        system=None,
        messages=(Message(role="user", content="Hi"),),
        max_tokens=1,
    )
    try:
        tokens = await claude.estimate(asked)
    except ProviderError as error:
        return Diagnosis(f"Model {model}", ok=False, note=str(error))
    note = f"known to the API; a one-word question is {tokens} tokens"
    return Diagnosis(f"Model {model}", ok=True, note=note)


def _writable(out: Path) -> Diagnosis:
    """Whether runs could be kept in `out`, checked without making it."""
    nearest = next(folder for folder in (out, *out.parents) if folder.exists())
    try:
        with tempfile.NamedTemporaryFile(dir=nearest):
            pass
    except OSError as error:
        note = f"can't write in {str(nearest)!r}: {error.strerror}"
        return Diagnosis("Runs folder", ok=False, note=note)
    made = "" if out.is_dir() else ", and would be made"
    return Diagnosis("Runs folder", ok=True, note=f"{out} is writable{made}")


async def _offline_run() -> Diagnosis:
    """One scripted case through the real runner, kept in a folder that is gone afterwards."""
    suite = Suite.model_validate(
        {
            "schema": 1,
            "name": "doctor",
            "target": {"provider": "fake"},
            "cases": [
                {"id": "hello", "input": "Hi", "checks": [{"type": "contains", "text": "hi"}]}
            ],
        }
    )
    providers = Providers(FakeProvider({"hello": ["Hi there"]}))
    with tempfile.TemporaryDirectory() as scratch:
        try:
            finished = await run_suite(suite, providers, out=Path(scratch))
        except (ProviderError, OSError) as error:
            return Diagnosis("Offline run", ok=False, note=f"a scripted run didn't finish: {error}")
    note = f"{finished.trials_passed} of {len(finished.scored)} passed"
    return Diagnosis("Offline run", ok=True, note=note)
