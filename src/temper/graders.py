"""Graders turn an answer into a pass or a fail, with a reason a person can read.

Each grader is a small validated model: its settings are its fields, and
`grade` is a pure function of the answer. Text comparisons ignore case and
spacing unless a check asks for exact case.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar, Final

from pydantic import BaseModel, ConfigDict, field_validator
from typing_extensions import override

from temper.errors import UnknownNameError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from temper.suite import Check


class Grade(BaseModel):
    """The verdict of one check on one answer."""

    model_config = ConfigDict(frozen=True)

    check: str
    passed: bool
    reason: str


class Grader(BaseModel, ABC):
    """A check that can grade an answer. Its fields are its settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @abstractmethod
    def grade(self, answer: str) -> Grade:
        """Grade one answer."""


def normalize(text: str, *, case_sensitive: bool = False) -> str:
    """Text as graders compare it: each run of whitespace becomes one space, and case is folded."""
    spaced = " ".join(text.split())
    return spaced if case_sensitive else spaced.casefold()


class TextGrader(Grader):
    """A grader that compares the answer with a piece of text."""

    name: ClassVar[str]

    text: str
    case_sensitive: bool = False

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the text to look for can't be blank")
        return value

    def _fold(self, value: str) -> str:
        return normalize(value, case_sensitive=self.case_sensitive)

    def _found_in(self, answer: str) -> bool:
        return self._fold(self.text) in self._fold(answer)

    def _verdict(self, *, passed: bool, reason: str) -> Grade:
        return Grade(check=f'{self.name} "{self.text}"', passed=passed, reason=reason)


class Equals(TextGrader):
    """Passes when the whole answer is the text."""

    name: ClassVar[str] = "equals"

    @override
    def grade(self, answer: str) -> Grade:
        passed = self._fold(answer) == self._fold(self.text)
        return self._verdict(passed=passed, reason="matches" if passed else "says something else")


class Contains(TextGrader):
    """Passes when the answer includes the text."""

    name: ClassVar[str] = "contains"

    @override
    def grade(self, answer: str) -> Grade:
        found = self._found_in(answer)
        reason = f'says "{self.text}"' if found else f'never says "{self.text}"'
        return self._verdict(passed=found, reason=reason)


class NotContains(TextGrader):
    """Passes when the answer leaves the text out."""

    name: ClassVar[str] = "not_contains"

    @override
    def grade(self, answer: str) -> Grade:
        said = self._found_in(answer)
        reason = f'says "{self.text}"' if said else f'avoids "{self.text}"'
        return self._verdict(passed=not said, reason=reason)


GRADERS: Final[Mapping[str, type[Grader]]] = {
    grader.name: grader for grader in (Equals, Contains, NotContains)
}


def build_grader(check: Check) -> Grader:
    """The grader a check names, with its settings validated.

    Raises:
        UnknownNameError: no grader has that name.
        pydantic.ValidationError: the settings don't fit that grader.
    """
    kind = GRADERS.get(check.type)
    if kind is None:
        raise UnknownNameError("check type", check.type, GRADERS)
    return kind.model_validate(check.settings)
