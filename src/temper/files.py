"""Reading the files a suite points at, so every failure arrives as one kind of error."""

from __future__ import annotations

from typing import TYPE_CHECKING

from temper.errors import UnreadableFileError

if TYPE_CHECKING:
    from pathlib import Path


def read_text(path: Path) -> str:
    """The file's text, read as UTF-8.

    Raises:
        UnreadableFileError: the file is missing, can't be opened, or isn't UTF-8 text.
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise UnreadableFileError(path, "it isn't UTF-8 text") from None
    except OSError as error:
        raise UnreadableFileError(path, error.strerror or str(error)) from None
