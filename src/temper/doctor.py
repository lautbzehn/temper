"""A check-up that proves the wiring: Python, the package, credentials, the API, and a run.

Each check says what it found in words a person can act on. None prints a
secret, and none spends money: the API is only asked to count tokens, which
is free, and the trial run answers from a script.
"""

from __future__ import annotations

import platform
import tempfile
from contextlib import aclosing
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING

from temper.errors import ProviderError
from temper.planning import Providers
from temper.providers import ClaudeProvider, ClaudeSettings, FakeProvider, Request
from temper.runner import run_suite
from temper.suite import Message, Suite

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5")
LEAST_PYTHON = (3, 11)


@dataclass(frozen=True, slots=True)
class Finding:
    """One check's outcome: what was checked, whether it's fine, and what was found."""

    name: str
    ok: bool
    note: str


async def examine(suite: Suite | None, out: Path) -> list[Finding]:
    """Run every check, in the order a person would fix them.

    With a suite, the models probed are its own; without one, Temper's
    defaults. The API is asked to count the tokens of one short request per
    model, which proves the credentials and the model name for free.
    """
    async with aclosing(ClaudeProvider.from_settings(ClaudeSettings())) as claude:
        findings = [_python(), _package(), _credentials(claude)]
        findings.extend([await _reachable(claude, model) for model in _models(suite)])
    folder = _writable(out)
    findings.append(folder)
    findings.append(await _offline_run(out if folder.ok else None))
    return findings


def _python() -> Finding:
    running = platform.python_version()
    fine = tuple(int(part) for part in running.split(".")[:2]) >= LEAST_PYTHON
    least = ".".join(str(part) for part in LEAST_PYTHON)
    return Finding(
        "Python", ok=fine, note=running if fine else f"{running}; Temper needs {least} or newer"
    )


def _package() -> Finding:
    return Finding("Temper", ok=True, note=version("temper-evals"))


def _credentials(claude: ClaudeProvider) -> Finding:
    source = claude.credentials_source()
    if source is None:
        note = "none found; set ANTHROPIC_API_KEY or sign in with `ant auth login`"
        return Finding("Credentials", ok=False, note=note)
    return Finding("Credentials", ok=True, note=f"{source}, never shown here")


def _models(suite: Suite | None) -> Sequence[str]:
    if suite is None:
        return DEFAULT_MODELS
    models = (
        [suite.target.model] if suite.target.provider == "claude" and suite.target.model else []
    )
    if suite.judged:
        models.append(suite.judge.model)
    return models or DEFAULT_MODELS


async def _reachable(claude: ClaudeProvider, model: str) -> Finding:
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
        return Finding(f"Model {model}", ok=False, note=str(error))
    return Finding(
        f"Model {model}", ok=True, note=f"answers; a one-word question is {tokens} tokens"
    )


async def _offline_run(out: Path | None) -> Finding:
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
    with tempfile.TemporaryDirectory(dir=out) as scratch:
        try:
            finished = await run_suite(
                suite, Providers(FakeProvider({"hello": ["Hi there"]})), out=Path(scratch)
            )
        except (ProviderError, OSError) as error:
            return Finding("Offline run", ok=False, note=f"a scripted run didn't finish: {error}")
    return Finding(
        "Offline run", ok=True, note=f"{finished.trials_passed} of {len(finished.scored)} passed"
    )


def _writable(out: Path) -> Finding:
    try:
        out.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=out):
            pass
    except OSError as error:
        return Finding(
            "Runs folder", ok=False, note=f"can't write in {str(out)!r}: {error.strerror}"
        )
    return Finding("Runs folder", ok=True, note=f"{out} is writable")
