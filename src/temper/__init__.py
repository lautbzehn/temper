"""Temper: test AI features the way you test code, and know when a difference is real.

Typical use from Python::

    suite = temper.load_suite("examples/dunder-mifflin/suite.yaml")
    provider = temper.build_provider(suite.target, suite.folder)
    run = asyncio.run(temper.run_suite(suite, provider, out=Path("runs")))
"""

from importlib.metadata import version

from temper.errors import ProviderError, RunError, SuiteError, TransientError, UnknownNameError
from temper.loading import load_suite
from temper.providers import build_provider
from temper.results import Run, RunFolder, RunOptions, TrialFailure, TrialResult
from temper.runner import (
    Plan,
    complete_run,
    estimate_suite,
    plan_run,
    provider_for,
    reopen_run,
    resume_run,
    run_suite,
    start_run,
)
from temper.suite import Suite

__version__ = version("temper-evals")

__all__ = [
    "Plan",
    "ProviderError",
    "Run",
    "RunError",
    "RunFolder",
    "RunOptions",
    "Suite",
    "SuiteError",
    "TransientError",
    "TrialFailure",
    "TrialResult",
    "UnknownNameError",
    "__version__",
    "build_provider",
    "complete_run",
    "estimate_suite",
    "load_suite",
    "plan_run",
    "provider_for",
    "reopen_run",
    "resume_run",
    "run_suite",
    "start_run",
]
