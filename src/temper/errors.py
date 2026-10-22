"""What can go wrong, said in words a person can act on."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path


def closest(name: str, options: Iterable[str]) -> str | None:
    """The option that looks most like `name`, when one is close enough to be a likely typo."""
    matches = difflib.get_close_matches(name, list(options), n=1)
    return matches[0] if matches else None


class UnknownNameError(LookupError):
    """A name that isn't one of the known choices, with a suggestion when one is near."""

    def __init__(self, kind: str, name: str, known: Iterable[str]) -> None:
        self.kind = kind
        self.name = name
        self.known = tuple(sorted(known))
        guess = closest(name, self.known)
        hint = f"did you mean {guess!r}?" if guess else f"choose from {', '.join(self.known)}"
        super().__init__(f"unknown {kind} {name!r}; {hint}")


class ProviderError(Exception):
    """A provider couldn't be set up or couldn't answer, and trying again wouldn't help."""


class TransientError(ProviderError):
    """A provider couldn't answer just now, but might on another try.

    `retry_after` is how long the provider asked to wait, in seconds, when it said.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class RunError(Exception):
    """A kept run that can't be used: its folder is incomplete, or its suite has changed."""


class UnreadableFileError(Exception):
    """A file that couldn't be read as UTF-8 text, and why, in words a person can act on."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"can't read {str(path)!r}: {reason}")


@dataclass(frozen=True, slots=True)
class Problem:
    """One thing wrong with a suite file, and where it is."""

    where: str
    message: str
    line: int | None = None
    column: int | None = None


class SuiteError(Exception):
    """A suite file that can't be used, with every problem found in it, in file order."""

    def __init__(self, path: Path, problems: Sequence[Problem]) -> None:
        self.path = path
        self.problems = tuple(sorted(problems, key=lambda p: (p.line or 0, p.column or 0)))
        super().__init__("\n".join(self.lines()))

    def lines(self) -> list[str]:
        """Each problem as `file:line:column: where: message`, a format editors turn into links."""
        return [self._line(problem) for problem in self.problems]

    def _line(self, problem: Problem) -> str:
        place = (self.path, problem.line, problem.column)
        prefix = ":".join(str(part) for part in place if part is not None)
        subject = f"{problem.where}: " if problem.where else ""
        return f"{prefix}: {subject}{problem.message}"
