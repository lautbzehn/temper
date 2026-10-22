"""Labels: what a person said about an answer, kept beside the run it came from."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict

from temper import jsonl
from temper.errors import BadLineError, RunError, UnreadableFileError

if TYPE_CHECKING:
    from pathlib import Path

FILE_NAME = "labels.jsonl"

# What a label is about: the case, the trial, and the check.
LabelKey = tuple[str, int, int]


class Label(BaseModel):
    """One person's call on whether one answer has one property.

    `answer` is the fingerprint of the answer the label is about, and
    `property` the wording the person read, so the label stays true to both
    whatever happens to the suite or the run afterwards.
    """

    model_config = ConfigDict(frozen=True)

    case_id: str
    trial: int
    check: int
    answer: str
    property: str
    passed: bool
    at: datetime


def key(label: Label) -> LabelKey:
    """What the label is about."""
    return (label.case_id, label.trial, label.check)


class Labels:
    """A labels file: every label in it, and a way to add one more the moment it's given."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def of(cls, run_path: Path) -> Self:
        """A run's own labels: `labels.jsonl` in its folder."""
        return cls(run_path / FILE_NAME)

    def read(self) -> list[Label]:
        """Every label in the file, or none at all when there's no file yet.

        Raises:
            RunError: the file can't be read, or holds a line that isn't a label.
        """
        if not self.path.exists():
            return []
        try:
            return list(jsonl.read(self.path, Label))
        except UnreadableFileError as error:
            raise RunError(f"can't read labels: {error}") from None
        except BadLineError as error:
            raise RunError(f"line {error.line} of {str(self.path)!r} isn't a label") from None

    def add(self, label: Label) -> None:
        """Keep one more label."""
        jsonl.append(self.path, label)
