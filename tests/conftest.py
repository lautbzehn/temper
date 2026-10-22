from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from hypothesis import settings

from tests.support import Files

if TYPE_CHECKING:
    from pathlib import Path

# Each property is tried on 500 generated inputs rather than Hypothesis's default 100.
settings.register_profile("temper", max_examples=500)
settings.load_profile("temper")


@pytest.fixture
def files(tmp_path: Path) -> Files:
    """A fresh folder to write suite files into."""
    return Files(tmp_path)
