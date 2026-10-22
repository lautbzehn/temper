"""Finding the check a suite names: a built-in grader, the judge, or one another package adds."""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from temper import plugins
from temper.errors import PluginError, UnknownNameError
from temper.graders import BUILT_IN, Grader, JudgeCheck

if TYPE_CHECKING:
    from collections.abc import Mapping

    from temper.suite import Case, Check


@cache
def check_kinds() -> Mapping[str, type[Grader | JudgeCheck]]:
    """Every kind of check by name: the built-in graders, the judge, and any a plugin adds.

    Found once and kept, since plugins come from installed packages and don't
    change while Temper runs.

    Raises:
        PluginError: a plugin can't be used, or takes a name that's already taken.
    """
    kinds: dict[str, type[Grader | JudgeCheck]] = {**BUILT_IN, JudgeCheck.name: JudgeCheck}
    for plugin in plugins.load("temper.graders"):
        added = plugin.value
        if not (isinstance(added, type) and issubclass(added, Grader)):
            raise PluginError(f"{plugin.source} isn't a Grader")
        name = getattr(added, "name", None)
        if not isinstance(name, str):
            raise PluginError(f"{plugin.source} doesn't say its name; set `name` on the class")
        if name in kinds:
            raise PluginError(f"{plugin.source} calls itself {name!r}, a name that's taken")
        kinds[name] = added
    return kinds


def build_check(check: Check) -> Grader | JudgeCheck:
    """The check a suite's entry names, with its settings validated.

    Raises:
        UnknownNameError: no check has that name.
        pydantic.ValidationError: the settings don't fit that check.
        PluginError: a plugin can't be used.
    """
    kinds = check_kinds()
    kind = kinds.get(check.type)
    if kind is None:
        raise UnknownNameError("check type", check.type, kinds)
    return kind.model_validate(check.settings)


def judge_checks(case: Case) -> list[tuple[int, JudgeCheck]]:
    """The checks of a case the judge decides, each with its position among the case's checks."""
    built = ((index, build_check(case.checks[index])) for index in case.judged)
    return [(index, check) for index, check in built if isinstance(check, JudgeCheck)]
