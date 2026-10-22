"""Temper: test AI features the way you test code, and know when a difference is real.

Typical use from Python::

    suite = temper.load_suite("examples/dunder-mifflin/suite.yaml")
    provider = temper.build_provider(suite.target, Path("examples/dunder-mifflin"))
    run = asyncio.run(temper.run_suite(suite, provider))
"""

from importlib.metadata import version

from temper.errors import ProviderError, SuiteError, UnknownNameError
from temper.loading import load_suite
from temper.providers import build_provider
from temper.results import Run, write_run
from temper.runner import run_suite
from temper.suite import Suite

__version__ = version("temper-evals")

__all__ = [
    "ProviderError",
    "Run",
    "Suite",
    "SuiteError",
    "UnknownNameError",
    "__version__",
    "build_provider",
    "load_suite",
    "run_suite",
    "write_run",
]
