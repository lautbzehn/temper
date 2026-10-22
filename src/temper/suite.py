"""The suite format: what a suite file may say, checked as it loads.

Schema version 1 is frozen against breaking changes. New optional fields may
still arrive, so a suite written today keeps loading tomorrow.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PositiveInt,
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


class Strict(BaseModel):
    """A frozen model that rejects unknown fields, so a typo fails loudly instead of quietly."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Message(Strict):
    """One turn of a conversation sent to the model under test."""

    role: Literal["user", "assistant"]
    content: str


class Check(BaseModel):
    """One check on an answer: the grader's name, plus that grader's own settings."""

    model_config = ConfigDict(extra="allow", frozen=True)

    type: str

    @property
    def settings(self) -> dict[str, Any]:
        """Everything in the check except its `type`, for the grader to validate."""
        return dict(self.model_extra or {})


class Case(Strict):
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


class Target(Strict):
    """The system under test: which provider and model answer, and how they're prompted."""

    provider: str
    model: str | None = None
    system: str | None = None
    system_file: str | None = None
    max_tokens: PositiveInt = 1024
    options: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_system_prompt(self) -> Self:
        if self.system is not None and self.system_file is not None:
            raise ValueError("give `system` or `system_file`, not both")
        return self


class Suite(Strict):
    """A whole suite: the system under test, and the cases it has to pass."""

    schema_version: Literal[1] = Field(alias="schema")
    name: str
    description: str = ""
    target: Target
    trials: PositiveInt = 1
    cases: tuple[Case, ...] = Field(min_length=1)

    @field_validator("cases")
    @classmethod
    def _unique_ids(cls, cases: tuple[Case, ...]) -> tuple[Case, ...]:
        counts = Counter(case.id for case in cases)
        if repeated := sorted(case_id for case_id, count in counts.items() if count > 1):
            raise ValueError(f"case ids must be unique; repeated: {', '.join(repeated)}")
        return cases
