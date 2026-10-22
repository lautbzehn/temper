"""Checks turn an answer into a grade a person can read: passed, failed, or no verdict, and why.

Most checks are code: a small validated model whose fields are its settings
and whose `grade` is a pure function of the answer. One, `judge`, is a
question for a model instead, and `judge.py` says how it is asked. Text
comparisons collapse each run of whitespace to one space and ignore case,
unless a check makes case count.
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Self

from pydantic import BaseModel, ConfigDict, Field, Strict, field_validator, model_validator
from typing_extensions import override

from temper.suite import JUDGE, Closed, Count, Message
from temper.wording import dollars, plural

if TYPE_CHECKING:
    from collections.abc import Mapping


class Answer(Closed):
    """One answer as the checks see it: its text, what was asked, and what answering took."""

    text: str
    conversation: tuple[Message, ...]
    latency_ms: float
    cost_usd: float | None = None

    @property
    def fingerprint(self) -> str:
        """A short hash of the conversation and the text: which answer this is, by name."""
        quoted = self.model_dump_json(include={"conversation", "text"})
        return hashlib.sha256(quoted.encode()).hexdigest()[:16]


class Grade(BaseModel):
    """The verdict of one check on one answer.

    `passed` is None when the check reached no verdict at all, which is not a
    failure: `reason` says what stood in the way. `cost_usd` is what reaching
    the grade cost, when a model was asked.
    """

    model_config = ConfigDict(frozen=True)

    check: str
    passed: bool | None
    reason: str
    cost_usd: float | None = None


class Grader(Closed, ABC):
    """A check decided in code. Its fields are its settings, and `grade` is pure."""

    name: ClassVar[str]

    @abstractmethod
    def grade(self, answer: Answer) -> Grade:
        """Grade one answer."""


def normalize(text: str, *, case_sensitive: bool = False) -> str:
    """Text as graders compare it: runs of whitespace become one space, and case is folded."""
    spaced = " ".join(text.split())
    return spaced if case_sensitive else spaced.casefold()


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("can't be blank")
    return value


class TextGrader(Grader):
    """A grader that compares the answer with a piece of text."""

    text: str
    case_sensitive: bool = False

    @field_validator("text")
    @classmethod
    def _has_text(cls, value: str) -> str:
        return _not_blank(value)

    def _fold(self, value: str) -> str:
        return normalize(value, case_sensitive=self.case_sensitive)

    def _found_in(self, answer: Answer) -> bool:
        return self._fold(self.text) in self._fold(answer.text)

    def _verdict(self, *, passed: bool, reason: str) -> Grade:
        return Grade(check=f'{self.name} "{self.text}"', passed=passed, reason=reason)


class Equals(TextGrader):
    """Passes when the whole answer is the text."""

    name: ClassVar[str] = "equals"

    @override
    def grade(self, answer: Answer) -> Grade:
        passed = self._fold(answer.text) == self._fold(self.text)
        return self._verdict(passed=passed, reason="matches" if passed else "says something else")


class Contains(TextGrader):
    """Passes when the answer includes the text."""

    name: ClassVar[str] = "contains"

    @override
    def grade(self, answer: Answer) -> Grade:
        found = self._found_in(answer)
        reason = f'says "{self.text}"' if found else f'never says "{self.text}"'
        return self._verdict(passed=found, reason=reason)


class NotContains(TextGrader):
    """Passes when the answer leaves the text out."""

    name: ClassVar[str] = "not_contains"

    @override
    def grade(self, answer: Answer) -> Grade:
        said = self._found_in(answer)
        reason = f'says "{self.text}"' if said else f'avoids "{self.text}"'
        return self._verdict(passed=not said, reason=reason)


class Matches(Grader):
    """Passes when a regular expression matches somewhere in the answer, as written."""

    name: ClassVar[str] = "matches"

    pattern: str

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as error:
            raise ValueError(f"isn't a regular expression: {error}") from None
        return value

    @override
    def grade(self, answer: Answer) -> Grade:
        found = re.search(self.pattern, answer.text)
        reason = f'matches at "{found.group()}"' if found else "never matches"
        return Grade(check=f"matches /{self.pattern}/", passed=found is not None, reason=reason)


class Length(Grader):
    """Passes when the answer's word count stays within the bounds given.

    `min_words` is 0 unless set, which is no bound at all, so a check may
    name either bound or both.
    """

    name: ClassVar[str] = "length"

    min_words: Annotated[int, Strict(), Field(ge=0)] = 0
    max_words: Count | None = None

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if self.max_words is None and not self.min_words:
            raise ValueError("give min_words, max_words, or both")
        if self.max_words is not None and self.min_words > self.max_words:
            raise ValueError("min_words can't be more than max_words")
        return self

    @override
    def grade(self, answer: Answer) -> Grade:
        words = len(answer.text.split())
        over = self.max_words is not None and words > self.max_words
        passed = words >= self.min_words and not over
        return Grade(check=f"length {self._bounds()}", passed=passed, reason=plural(words, "word"))

    def _bounds(self) -> str:
        if self.max_words is None:
            return f"at least {plural(self.min_words, 'word')}"
        if not self.min_words:
            return f"at most {plural(self.max_words, 'word')}"
        return f"{self.min_words} to {plural(self.max_words, 'word')}"


class Json(Grader):
    """Passes when the whole answer is JSON, and an object with the named keys if any are named."""

    name: ClassVar[str] = "json"

    keys: tuple[str, ...] = ()

    @override
    def grade(self, answer: Answer) -> Grade:
        try:
            value = json.loads(answer.text, parse_constant=_not_json)
        except json.JSONDecodeError as error:
            reason = f"isn't JSON: {error.msg} at line {error.lineno}, column {error.colno}"
            return self._verdict(passed=False, reason=reason)
        except ValueError as error:
            return self._verdict(passed=False, reason=f"isn't JSON: {error}")
        if not self.keys:
            return self._verdict(passed=True, reason="is JSON")
        if not isinstance(value, dict):
            return self._verdict(passed=False, reason="is JSON, but not an object")
        missing = [key for key in self.keys if key not in value]
        reason = f"lacks {', '.join(missing)}" if missing else "has every key"
        return self._verdict(passed=not missing, reason=reason)

    def _verdict(self, *, passed: bool, reason: str) -> Grade:
        named = f" with {', '.join(self.keys)}" if self.keys else ""
        return Grade(check=f"json{named}", passed=passed, reason=reason)


def _not_json(constant: str) -> object:
    """Refuse the NaN and Infinity that Python's parser allows and JSON doesn't."""
    raise ValueError(f"{constant} isn't JSON")


class Cost(Grader):
    """Passes when the answer cost at most `max_usd` at list price."""

    name: ClassVar[str] = "cost"

    max_usd: float = Field(gt=0)

    @override
    def grade(self, answer: Answer) -> Grade:
        check = f"cost at most {dollars(self.max_usd)}"
        if answer.cost_usd is None:
            reason = "this model has no list price, so the cost isn't known"
            return Grade(check=check, passed=None, reason=reason)
        passed = answer.cost_usd <= self.max_usd
        return Grade(check=check, passed=passed, reason=f"cost {dollars(answer.cost_usd)}")


class Latency(Grader):
    """Passes when the answer arrived within `max_s` seconds, retries included."""

    name: ClassVar[str] = "latency"

    max_s: float = Field(gt=0)

    @override
    def grade(self, answer: Answer) -> Grade:
        seconds = answer.latency_ms / 1000
        return Grade(
            check=f"latency at most {self.max_s:g} s",
            passed=seconds <= self.max_s,
            reason=f"answered in {seconds:.1f} s",
        )


class JudgeCheck(Closed):
    """A check the judge decides, not code: whether the answer has one property, in plain words."""

    name: ClassVar[str] = JUDGE

    property: str

    @field_validator("property")
    @classmethod
    def _has_property(cls, value: str) -> str:
        return _not_blank(value)


BUILT_IN: Final[Mapping[str, type[Grader]]] = {
    grader.name: grader
    for grader in (Equals, Contains, NotContains, Matches, Length, Json, Cost, Latency)
}
