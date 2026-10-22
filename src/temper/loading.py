"""Loading a suite file: YAML in, a validated suite out, or every problem with its line.

The file is parsed once into both data and a map from each location in the
document to where it starts, so any problem found later, by Pydantic or by
Temper's own checks, can point at a line and column. The suite's shape, its
checks, and its target are each checked on their own, so a typo in one place
never hides a mistake in another.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml
from pydantic import BaseModel, ValidationError

from temper.errors import Problem, ProviderError, SuiteError, UnknownNameError, closest
from temper.graders import GRADERS, build_grader
from temper.providers import FakeSettings, build_provider
from temper.suite import Case, Check, Message, Suite, Target

if TYPE_CHECKING:
    from collections.abc import Iterator
    from os import PathLike

    from pydantic_core import ErrorDetails

Loc = tuple[str | int, ...]
Marks = dict[Loc, yaml.Mark]


def _field_names(*models: type[BaseModel]) -> frozenset[str]:
    return frozenset(
        field.alias or name for model in models for name, field in model.model_fields.items()
    )


FIELD_NAMES: Final = _field_names(Suite, Target, Case, Message, FakeSettings, *GRADERS.values())


def load_suite(path: str | PathLike[str]) -> Suite:
    """Load a suite file and check it, reporting every problem at once.

    Raises:
        SuiteError: the file can't be read, isn't valid YAML, or doesn't describe a usable suite.
    """
    source = Path(path)
    data, marks = _parse(source)
    suite, problems = _validate(data, marks)
    problems += [*_check_problems(data, marks), *_target_problems(data, source.parent, marks)]
    if suite is None or problems:
        raise SuiteError(source, problems)
    return _with_system_prompt(suite, source.parent)


def _parse(path: Path) -> tuple[object, Marks]:
    """The file's data, and where each location in it starts."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SuiteError(path, [Problem("", f"can't read the file: {error.strerror}")]) from None

    loader = yaml.SafeLoader(text)
    try:
        node = loader.get_single_node()
        if node is None:
            raise SuiteError(path, [Problem("", "the file is empty")])
        return loader.construct_document(node), {(): node.start_mark, **dict(_marks(node))}
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark
        line, column = (mark.line + 1, mark.column + 1) if mark else (None, None)
        problem = Problem("", f"this isn't valid YAML: {error.problem}", line, column)
        raise SuiteError(path, [problem]) from None
    finally:
        loader.dispose()


def _marks(node: yaml.Node, loc: Loc = ()) -> Iterator[tuple[Loc, yaml.Mark]]:
    """Each location under `node`, with where it starts: a mapping entry at its key."""
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            yield (*loc, key.value), key.start_mark
            yield from _marks(value, (*loc, key.value))
    elif isinstance(node, yaml.SequenceNode):
        for index, item in enumerate(node.value):
            yield (*loc, index), item.start_mark
            yield from _marks(item, (*loc, index))


def _validate(data: object, marks: Marks) -> tuple[Suite | None, list[Problem]]:
    """The suite, if its shape is right, and the problems with its shape if not."""
    try:
        return Suite.model_validate(data), []
    except ValidationError as error:
        return None, [_problem(details, marks) for details in _explained(error.errors())]


def _explained(errors: list[ErrorDetails]) -> list[ErrorDetails]:
    """Drop a list's "too short" error when errors in its own items already explain it."""

    def is_echo(error: ErrorDetails) -> bool:
        loc = error["loc"]
        return error["type"] == "too_short" and any(
            len(other["loc"]) > len(loc) and other["loc"][: len(loc)] == loc for other in errors
        )

    return [error for error in errors if not is_echo(error)]


def _problem(details: ErrorDetails, marks: Marks, prefix: Loc = ()) -> Problem:
    """A Pydantic error, retold in plain words at the nearest line."""
    where, message = _describe((*prefix, *details["loc"]), details)
    return _at(where, message, marks)


def _describe(loc: Loc, details: ErrorDetails) -> tuple[Loc, str]:
    """Plain words for a validation error, and the location they're about."""
    parent, last = loc[:-1], loc[-1] if loc else ""
    match details["type"]:
        case "missing":
            return parent, f"missing required field {last!r}"
        case "extra_forbidden":
            guess = closest(str(last), FIELD_NAMES)
            return loc, f"unknown field; did you mean {guess!r}?" if guess else "unknown field"
        case "too_short":
            least = details.get("ctx", {}).get("min_length", 1)
            return (
                loc,
                "needs at least one entry" if least == 1 else f"needs at least {least} entries",
            )
        case "string_type" if isinstance(details["input"], bool):
            return loc, "expected text, but YAML read this as true or false; put it in quotes"
        case _:
            return loc, details["msg"].removeprefix("Value error, ").removeprefix("Input ")


def _at(loc: Loc, message: str, marks: Marks) -> Problem:
    """A problem about `loc`, placed at the closest location the file actually has."""
    mark = next(marks[loc[:end]] for end in range(len(loc), -1, -1) if loc[:end] in marks)
    return Problem(_where(loc), message, mark.line + 1, mark.column + 1)


def _where(loc: Loc) -> str:
    """`('cases', 2, 'checks', 0)` written the way a person would: `cases[2].checks[0]`."""
    return "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in loc).lstrip(".")


def _check_problems(data: object, marks: Marks) -> Iterator[Problem]:
    """Each check must name a known grader, with settings that grader accepts."""
    for case_index, case in enumerate(_entries(data, "cases")):
        for check_index, entry in enumerate(_entries(case, "checks")):
            here: Loc = ("cases", case_index, "checks", check_index)
            try:
                check = Check.model_validate(entry)
            except ValidationError:
                continue  # the shape check has already said what is wrong here
            try:
                build_grader(check)
            except UnknownNameError as error:
                yield _at((*here, "type"), str(error), marks)
            except ValidationError as error:
                yield from (_problem(details, marks, here) for details in error.errors())


def _target_problems(data: object, base_dir: Path, marks: Marks) -> Iterator[Problem]:
    """The system prompt file must exist, and the provider must be ready to answer."""
    try:
        target = Target.model_validate(data.get("target") if isinstance(data, dict) else None)
    except ValidationError:
        return  # the shape check has already said what is wrong here
    if target.system_file is not None and not (base_dir / target.system_file).is_file():
        yield _at(("target", "system_file"), f"can't find {target.system_file!r}", marks)
    try:
        build_provider(target, base_dir)
    except UnknownNameError as error:
        yield _at(("target", "provider"), str(error), marks)
    except ValidationError as error:
        yield from (_problem(details, marks, ("target", "options")) for details in error.errors())
    except ProviderError as error:
        yield _at(("target", "options"), str(error), marks)


def _entries(data: object, key: str) -> list[object]:
    """`data[key]`, when `data` is a mapping and that value is a list, or else nothing."""
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, list) else []


def _with_system_prompt(suite: Suite, base_dir: Path) -> Suite:
    """Read `system_file` into `system`, so nothing after loading touches the file system."""
    target = suite.target
    if target.system_file is None:
        return suite
    system = (base_dir / target.system_file).read_text(encoding="utf-8")
    resolved = target.model_copy(update={"system": system, "system_file": None})
    return suite.model_copy(update={"target": resolved})
