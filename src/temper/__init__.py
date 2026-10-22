"""Temper: test AI features the way you test code, and know when a difference is real.

Typical use from Python::

    suite = temper.load_suite("examples/dunder-mifflin/suite.yaml")
    providers = temper.providers_for(suite, temper.RunOptions())
    run = asyncio.run(temper.run_suite(suite, providers, out=Path("runs")))
"""

from importlib.metadata import version

from temper.calibration import Calibration, calibrate
from temper.errors import (
    PluginError,
    ProviderError,
    RunError,
    SuiteError,
    TransientError,
    UnknownNameError,
)
from temper.graders import Answer, Grade, Grader
from temper.labels import Label
from temper.loading import load_suite
from temper.planning import Plan, Providers, estimate_suite, plan_run, providers_for
from temper.providers import build_judge, build_provider
from temper.results import Run, RunFolder, RunOptions, TrialFailure, TrialResult
from temper.runner import complete_run, reopen_run, resume_run, run_suite, start_run
from temper.suite import Suite

__version__ = version("temper-evals")

__all__ = [
    "Answer",
    "Calibration",
    "Grade",
    "Grader",
    "Label",
    "Plan",
    "PluginError",
    "ProviderError",
    "Providers",
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
    "build_judge",
    "build_provider",
    "calibrate",
    "complete_run",
    "estimate_suite",
    "load_suite",
    "plan_run",
    "providers_for",
    "reopen_run",
    "resume_run",
    "run_suite",
    "start_run",
]
