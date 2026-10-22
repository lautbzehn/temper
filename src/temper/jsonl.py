"""Records kept one JSON object per line: appended as they happen, read back whole."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel, ValidationError

from temper.errors import BadLineError
from temper.files import read_text

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

Record = TypeVar("Record", bound=BaseModel)


def append(path: Path, record: BaseModel) -> None:
    """Add one record to the end of the file, making the file if it's new."""
    with path.open("a", encoding="utf-8") as lines:
        lines.write(record.model_dump_json() + "\n")


def read(path: Path, kind: type[Record]) -> Iterator[Record]:
    """Each record in the file as a `kind`.

    Raises:
        UnreadableFileError: the file can't be read.
        BadLineError: a line isn't a `kind`.
    """
    for number, line in enumerate(read_text(path).splitlines(), 1):
        if line.strip():
            try:
                yield kind.model_validate_json(line)
            except ValidationError as error:
                raise BadLineError(path, number) from error
