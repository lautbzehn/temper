"""Where answers come from: the providers, and how a suite's target picks one."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from temper.errors import UnknownNameError
from temper.providers import claude, fake, replay
from temper.providers.base import Completion, Provider, Request, Status, Usage
from temper.providers.claude import ClaudeProvider, ClaudeSettings
from temper.providers.fake import FakeProvider, FakeSettings
from temper.providers.replay import Recording, ReplayProvider, ReplaySettings

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from temper.suite import Closed, Target

PROVIDERS: Final[Mapping[str, Callable[[Target, Path], Provider]]] = {
    "claude": claude.build,
    "fake": fake.build,
    "replay": replay.build,
}

SETTINGS: Final[Mapping[str, type[Closed]]] = {
    "claude": ClaudeSettings,
    "fake": FakeSettings,
    "replay": ReplaySettings,
}


def build_provider(target: Target, base_dir: Path) -> Provider:
    """The provider a suite's target names, set up from its options.

    Paths in the options are read relative to `base_dir`, usually `suite.folder`.

    Raises:
        UnknownNameError: no provider has that name.
        pydantic.ValidationError: the options don't fit that provider.
        ProviderError: the provider couldn't be set up.
    """
    build = PROVIDERS.get(target.provider)
    if build is None:
        raise UnknownNameError("provider", target.provider, PROVIDERS)
    return build(target, base_dir)


__all__ = [
    "PROVIDERS",
    "SETTINGS",
    "ClaudeProvider",
    "ClaudeSettings",
    "Completion",
    "FakeProvider",
    "FakeSettings",
    "Provider",
    "Recording",
    "ReplayProvider",
    "ReplaySettings",
    "Request",
    "Status",
    "Usage",
    "build_provider",
]
