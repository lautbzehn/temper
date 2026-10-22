"""Things other packages add to Temper, found through entry points.

A package that ships a grader lists it under the `temper.graders` group in
its own metadata, and Temper finds it once that package is installed. Each
one comes with where it came from, so whoever checks it can say which
package to look at when it isn't what it should be.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points

from temper.errors import PluginError


@dataclass(frozen=True, slots=True)
class Plugin:
    """One registered object, and the plugin and package it came from."""

    source: str
    value: object


def load(group: str) -> list[Plugin]:
    """Everything registered under `group`, loaded.

    Raises:
        PluginError: an entry can't be loaded.
    """
    found: list[Plugin] = []
    for entry in entry_points(group=group):
        source = _describe(entry)
        try:
            found.append(Plugin(source, entry.load()))
        except Exception as error:
            raise PluginError(f"{source} can't be loaded: {error}") from error
    return found


def _describe(entry: EntryPoint) -> str:
    package = entry.dist.name if entry.dist is not None else "an unknown package"
    return f"plugin {entry.name!r} from {package}"
