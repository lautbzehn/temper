from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.support import Files

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def files(tmp_path: Path) -> Files:
    """A fresh folder to write suite files into."""
    return Files(tmp_path)
