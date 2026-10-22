from __future__ import annotations

import json
import sys
import textwrap
from collections.abc import Callable
from importlib.metadata import EntryPoint
from typing import TYPE_CHECKING

import pytest

from temper import plugins
from temper.checks import build_check, check_kinds
from temper.errors import PluginError
from temper.graders import Grader
from temper.loading import load_suite
from temper.suite import Check
from tests.support import seen

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from tests.support import Files

GOOD = """
    from typing import ClassVar

    from temper.graders import Answer, Grade, Grader


    class Shout(Grader):
        name: ClassVar[str] = "shouts"

        text: str

        def grade(self, answer: Answer) -> Grade:
            loud = self.text.upper() in answer.text
            reason = "loud" if loud else "quiet"
            return Grade(check=f"shouts {self.text}", passed=loud, reason=reason)
"""

Install = Callable[[str, str], None]


@pytest.fixture
def install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Install]:
    """Installs a pretend package that registers `Shout` from its module as a Temper grader."""

    def installed(module: str, source: str) -> None:
        (tmp_path / f"{module}.py").write_text(textwrap.dedent(source), encoding="utf-8")
        info = tmp_path / f"{module}-1.0.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {module}\nVersion: 1.0\n")
        (info / "entry_points.txt").write_text(f"[temper.graders]\nshout = {module}:Shout\n")
        monkeypatch.delitem(sys.modules, module, raising=False)

    monkeypatch.syspath_prepend(tmp_path)
    check_kinds.cache_clear()
    yield installed
    check_kinds.cache_clear()


def test_an_installed_grader_is_a_check_like_any_other(install: Install, files: Files) -> None:
    install("shouty", GOOD)

    built = build_check(Check.model_validate({"type": "shouts", "text": "now"}))

    assert isinstance(built, Grader)
    assert built.grade(seen("Do it NOW")).passed
    assert check_kinds()["shouts"] is type(built)

    files.write("replies.yaml", "a: NOW\n")
    path = files.write(
        "suite.yaml",
        """
        schema: 1
        name: plugged
        target: {provider: fake, options: {replies: replies.yaml}}
        cases:
          - {id: a, input: Hi, checks: [{type: shouts, text: now}]}
        """,
    )
    assert load_suite(path).cases[0].checks[0].type == "shouts"


@pytest.mark.parametrize(
    ("source", "complaint"),
    [
        ("Shout = 42\n", "plugin 'shout' from shouty isn't a Grader"),
        (
            GOOD.replace('name: ClassVar[str] = "shouts"', ""),
            "plugin 'shout' from shouty doesn't say its name; set `name` on the class",
        ),
        (
            GOOD.replace('"shouts"', '"contains"'),
            "plugin 'shout' from shouty calls itself 'contains', a name that's taken",
        ),
        ('raise RuntimeError("boom")\n', "plugin 'shout' from shouty can't be loaded: boom"),
    ],
)
def test_a_plugin_that_is_not_a_grader_is_refused_by_name(
    install: Install, source: str, complaint: str
) -> None:
    install("shouty", source)

    with pytest.raises(PluginError, match=complaint):
        check_kinds()


def test_an_entry_point_without_a_package_is_still_named(monkeypatch: pytest.MonkeyPatch) -> None:
    loose = EntryPoint("loads", "json:loads", "temper.graders")
    monkeypatch.setattr("temper.plugins.entry_points", lambda **_: [loose])

    assert plugins.load("temper.graders") == [
        plugins.Plugin("plugin 'loads' from an unknown package", json.loads)
    ]
