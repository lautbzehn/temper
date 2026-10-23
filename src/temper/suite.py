"""The suite format: what a suite file may say, checked as it loads.

Schema version 1 is frozen against breaking changes. New optional fields may
still arrive, so a suite written today keeps loading tomorrow.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PrivateAttr,
    Strict,
    ValidationInfo,
    field_validator,
    model_validator,
)

_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")


def _check_id(value: str) -> str:
    if not _ID.fullmatch(value):
        raise ValueError(
            "ids use lowercase letters, digits, '.', '-' and '_', and start with a letter or digit"
        )
    return value


CaseId = Annotated[str, Field(max_length=64), AfterValidator(_check_id)]

# The one check a model decides instead of code. `graders.JudgeCheck` answers to it.
JUDGE = "judge"

# A positive whole number, as written: YAML's `yes` and "3" are not quietly read as numbers.
Count = Annotated[int, Strict(), Field(gt=0)]


class Closed(BaseModel):
    """A frozen model closed to unknown fields, so a typo fails loudly instead of quietly."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Message(Closed):
    """One turn of a conversation sent to the model under test."""

    role: Literal["user", "assistant"]
    content: str


class Check(BaseModel):
    """One check on an answer: the grader's name, plus that grader's own settings."""

    model_config = ConfigDict(extra="allow", frozen=True)

    type: str

    @property
    def settings(self) -> dict[str, object]:
        """Everything in the check except its `type`, for the grader to validate."""
        return dict(self.model_extra or {})


class Case(Closed):
    """One scenario: what to ask, and what a good answer must do."""

    id: CaseId
    input: str | None = None
    messages: Annotated[tuple[Message, ...], Field(min_length=1)] | None = None
    tags: tuple[str, ...] = ()
    checks: tuple[Check, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _one_way_to_ask(self) -> Self:
        if (self.input is None) == (self.messages is None):
            raise ValueError("give exactly one of `input` or `messages`")
        return self

    @property
    def conversation(self) -> tuple[Message, ...]:
        """The messages to send, with a plain `input` read as a single user turn."""
        if self.input is not None:
            return (Message(role="user", content=self.input),)
        return self.messages or ()

    @property
    def judged(self) -> tuple[int, ...]:
        """The positions of the checks the judge decides, counting from 0."""
        return tuple(index for index, check in enumerate(self.checks) if check.type == JUDGE)


class Target(Closed):
    """The system under test: which provider and model answer, and how they're prompted."""

    provider: str
    model: str | None = None
    system: str | None = None
    system_file: str | None = None
    max_tokens: Count = 1024
    options: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_system_prompt(self) -> Self:
        if self.system is not None and self.system_file is not None:
            raise ValueError("give `system` or `system_file`, not both")
        return self


class Judge(Closed):
    """Who decides a `judge` check: the model, how long its verdict may run, and its options.

    The judge is a Claude model asked through the same provider as a Claude
    target, so `options` takes what that provider takes. It is never the
    model under test: a suite that judges a model with itself doesn't load.
    """

    model: str = "claude-opus-5-5"
    max_tokens: Count = 512
    options: dict[str, JsonValue] = Field(default_factory=dict)


class Suite(Closed):
    """A whole suite: the system under test, the cases it has to pass, and who judges them."""

    schema_version: Literal[1] = Field(alias="schema")
    name: str
    description: str = ""
    target: Target
    judge: Judge = Judge()
    trials: Count = 1
    cases: tuple[Case, ...] = Field(min_length=1)

    _path: Path | None = PrivateAttr(default=None)

    @property
    def path(self) -> Path | None:
        """The file this suite was loaded from, or None for a suite built in code.

        `load_suite` passes the path as validation context.
        """
        return self._path

    @property
    def folder(self) -> Path:
        """The folder this suite's relative paths are read from: its file's, or the current one."""
        return self._path.parent if self._path is not None else Path()

    @property
    def judged(self) -> bool:
        """Whether any case has a check the judge decides."""
        return any(case.judged for case in self.cases)

    def with_system(self, system: str) -> Suite:
        """The suite answered with `system` as its system prompt, held inline.

        Inline, so a run never depends on a prompt file again once it has
        started, and so two prompts can be compared on the very same cases.
        """
        target = self.target.model_copy(update={"system": system, "system_file": None})
        return self.model_copy(update={"target": target})

    @model_validator(mode="after")
    def _remember_path(self, info: ValidationInfo) -> Self:
        if isinstance(info.context, dict) and "path" in info.context:
            self._path = Path(info.context["path"])
        return self

    @field_validator("cases")
    @classmethod
    def _unique_ids(cls, cases: tuple[Case, ...]) -> tuple[Case, ...]:
        counts = Counter(case.id for case in cases)
        if repeated := sorted(case_id for case_id, count in counts.items() if count > 1):
            raise ValueError(f"case ids must be unique; repeated: {', '.join(repeated)}")
        return cases
