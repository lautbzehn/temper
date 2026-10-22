"""Loading a suite file: YAML in, a validated suite out, or every problem with its line.

The file is parsed once into both data and a map from each location in the
document to where it starts, so any problem found later, by Pydantic or by
Temper's own checks, can point at a line and column. The suite's shape, its
checks, its judge, and its target are each checked on their own, so a typo in
one place never hides a mistake in another.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml
from pydantic import BaseModel, ValidationError

from temper.checks import build_check, check_kinds
from temper.errors import (
    Problem,
    ProviderError,
    SuiteError,
    UnknownNameError,
    UnreadableFileError,
    closest,
)
from temper.files import read_text
from temper.providers import SETTINGS, ClaudeSettings, build_provider, same_model
from temper.suite import Case, Check, Judge, Message, Suite, Target

if TYPE_CHECKING:
    from collections.abc import Iterator
    from os import PathLike

    from pydantic_core import ErrorDetails

Loc = tuple[str | int, ...]
Marks = dict[Loc, yaml.Mark]
Places = dict[Loc, tuple[str, frozenset[str]]]

_OPTIONS: Final[Loc] = ("target", "options")
_JUDGE_OPTIONS: Final[Loc] = ("judge", "options")


def _field_names(*models: type[BaseModel]) -> frozenset[str]:
    return frozenset(
        field.alias or name for model in models for name, field in model.model_fields.items()
    )


def _places(provider: str | None) -> Places:
    """Each kind of mapping in a suite, by where it sits: how to say so, and its fields.

    List positions are left out of the places. The options are the named
    provider's own, or every provider's when the name isn't known.
    """
    known = SETTINGS.get(provider) if provider is not None else None
    settings = [known] if known is not None else list(SETTINGS.values())
    return {
        (): ("at the top level", _field_names(Suite)),
        ("target",): ("under target", _field_names(Target)),
        _OPTIONS: ("under target.options", _field_names(*settings)),
        ("judge",): ("under judge", _field_names(Judge)),
        _JUDGE_OPTIONS: ("under judge.options", _field_names(ClaudeSettings)),
        ("cases",): ("in a case", _field_names(Case)),
        ("cases", "messages"): ("in a message", _field_names(Message)),
        ("cases", "checks"): ("in a check", _field_names(Check, *check_kinds().values())),
    }


@dataclass(frozen=True, slots=True)
class _Document:
    """A parsed suite file.

    Its data, where each location starts, which provider it names, and any key
    it gives twice.
    """

    data: object
    marks: Marks
    provider: str | None
    repeated: list[Problem]

    @property
    def places(self) -> Places:
        return _places(self.provider)


def load_suite(path: str | PathLike[str]) -> Suite:
    """Load a suite file and check it, reporting every problem at once.

    The suite remembers its file as `suite.path`, and its folder, where its
    relative paths are read from, as `suite.folder`.

    Raises:
        SuiteError: the file can't be read, isn't valid YAML, or doesn't describe a usable suite.
        PluginError: a grader another package registered can't be used.
    """
    source = Path(path)
    document = _parse(source)
    suite, shape = _validate(document, source)
    system, target = _check_target(document, source.parent)
    checks = [*_check_problems(document), *_check_judge(document, suite)]
    problems = [*shape, *document.repeated, *checks, *target]
    if suite is None or problems:
        raise SuiteError(source, problems)
    return suite if system is None else _with_system_prompt(suite, system)


def _parse(path: Path) -> _Document:
    """Read and parse the file once, keeping where each location in it starts."""
    try:
        text = read_text(path)
    except UnreadableFileError as error:
        raise SuiteError(path, [Problem("", f"can't read the file: {error.reason}")]) from None

    try:
        loader = yaml.SafeLoader(text)
        try:
            node = loader.get_single_node()
            if node is None:
                raise SuiteError(path, [Problem("", "the file is empty")])
            return _document(loader.construct_document(node), node)
        finally:
            loader.dispose()
    except yaml.YAMLError as error:
        raise SuiteError(path, [_yaml_problem(error)]) from None


def _yaml_problem(error: yaml.YAMLError) -> Problem:
    """A YAML syntax error, at its line when PyYAML knows the line."""
    if isinstance(error, yaml.MarkedYAMLError) and error.problem_mark is not None:
        mark = error.problem_mark
        return Problem(
            "", f"this isn't valid YAML: {error.problem}", mark.line + 1, mark.column + 1
        )
    return Problem("", f"this isn't valid YAML: {str(error).splitlines()[0]}")


def _document(data: object, root: yaml.Node) -> _Document:
    """The parsed data with its marks, noting each key a mapping gives twice.

    YAML quietly keeps the last of two equal keys, so a repeat is reported as a
    problem, once, and not again for everything nested under it.
    """
    marks: Marks = {(): root.start_mark}
    repeated: dict[Loc, Problem] = {}
    for loc, mark in _marks(root):
        earlier = marks.get(loc)
        if earlier is not None and not any(loc[:end] in repeated for end in range(len(loc))):
            message = f"given twice (first on line {earlier.line + 1}); YAML keeps only this one"
            repeated[loc] = Problem(_where(loc), message, mark.line + 1, mark.column + 1)
        marks[loc] = mark
    provider = _entry(_entry(data, "target"), "provider")
    return _document_of(data, marks, provider, list(repeated.values()))


def _document_of(
    data: object, marks: Marks, provider: object, repeated: list[Problem]
) -> _Document:
    return _Document(data, marks, provider if isinstance(provider, str) else None, repeated)


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


def _validate(document: _Document, path: Path) -> tuple[Suite | None, list[Problem]]:
    """The suite, if its shape is right, and the problems with its shape if not."""
    try:
        return Suite.model_validate(document.data, context={"path": path}), []
    except ValidationError as error:
        errors = _explained(error.errors())
        return None, [_problem(details, document) for details in errors]


def _explained(errors: list[ErrorDetails]) -> list[ErrorDetails]:
    """Drop a list's "too short" error when errors in its own items already explain it."""

    def is_echo(error: ErrorDetails) -> bool:
        loc = error["loc"]
        return error["type"] == "too_short" and any(
            len(other["loc"]) > len(loc) and other["loc"][: len(loc)] == loc for other in errors
        )

    return [error for error in errors if not is_echo(error)]


def _problem(details: ErrorDetails, document: _Document, prefix: Loc = ()) -> Problem:
    """A Pydantic error, retold in plain words at the nearest line."""
    where, message = _describe((*prefix, *details["loc"]), details, document)
    return _at(where, message, document.marks)


def _describe(loc: Loc, details: ErrorDetails, document: _Document) -> tuple[Loc, str]:
    """Plain words for a validation error, and the location they're about.

    A missing field is about the mapping it's missing from; anything else is
    about the value at `loc`.
    """
    if details["type"] == "missing":
        return loc[:-1], f"missing required field {loc[-1]!r}"
    return loc, _message(loc, details, document)


# Pydantic error types whose plain-words message doesn't depend on the value.
_PLAIN: Final = {
    "int_type": "expected a whole number",
    "int_parsing": "expected a whole number",
    "int_from_float": "expected a whole number",
    "list_type": "expected a list",
    "tuple_type": "expected a list",
    "dict_type": "expected a mapping of names to values",
    "model_type": "expected a mapping of names to values",
    "model_attributes_type": "expected a mapping of names to values",
    "invalid-json-value": "expected plain text, a number, true or false, a list, or a mapping",
}


def _message(loc: Loc, details: ErrorDetails, document: _Document) -> str:
    found = details["input"]
    match details["type"]:
        case "extra_forbidden":
            message = _unknown_field(loc, document)
        case "too_short":
            least = details.get("ctx", {}).get("min_length", 1)
            message = f"needs at least {'one entry' if least == 1 else f'{least} entries'}"
        case "string_type" if isinstance(found, bool | int | float):
            read_as = "true or false" if isinstance(found, bool) else "a number"
            message = f"expected text, but YAML read this as {read_as}; put it in quotes"
        case kind if kind in _PLAIN:
            message = _PLAIN[kind]
        case _:
            message = details["msg"].removeprefix("Value error, ").removeprefix("Input ")
    return message


def _unknown_field(loc: Loc, document: _Document) -> str:
    """Why a field isn't allowed where it is: it belongs somewhere else, or it's a typo."""
    name = str(loc[-1])
    here = tuple(part for part in loc[:-1] if isinstance(part, str))
    places = document.places
    homes = [label for place, (label, fields) in places.items() if name in fields and place != here]
    if homes:
        return f"not a field here; it goes {homes[0]}"
    _, fields = places.get(here, ("", frozenset()))
    if guess := closest(name, fields):
        return f"unknown field; did you mean {guess!r}?"
    if here == _OPTIONS and document.provider in SETTINGS:
        return f"not an option of the {document.provider} provider, which takes {_listed(fields)}"
    if here == _JUDGE_OPTIONS:
        return f"not an option the judge takes; it takes {_listed(fields)}"
    return "unknown field"


def _listed(names: frozenset[str]) -> str:
    return ", ".join(sorted(names))


def _at(loc: Loc, message: str, marks: Marks) -> Problem:
    """A problem about `loc`, placed at the closest location the file actually has.

    The marks always hold the document's root, `()`, so a place is always found.
    """
    mark = next(marks[loc[:end]] for end in range(len(loc), -1, -1) if loc[:end] in marks)
    return Problem(_where(loc), message, mark.line + 1, mark.column + 1)


def _where(loc: Loc) -> str:
    """`('cases', 2, 'checks', 0)` written the way a person would: `cases[2].checks[0]`."""
    return "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in loc).lstrip(".")


def _check_problems(document: _Document) -> Iterator[Problem]:
    """Each check must name a known grader, with settings that grader accepts."""
    for case_index, case in enumerate(_entries(document.data, "cases")):
        for check_index, entry in enumerate(_entries(case, "checks")):
            here: Loc = ("cases", case_index, "checks", check_index)
            try:
                check = Check.model_validate(entry)
            except ValidationError:
                continue  # the shape check has already said what is wrong here
            try:
                build_check(check)
            except UnknownNameError as error:
                yield _at((*here, "type"), str(error), document.marks)
            except ValidationError as error:
                yield from (_problem(details, document, here) for details in error.errors())


def _check_judge(document: _Document, suite: Suite | None) -> Iterator[Problem]:
    """The judge's options must be Claude's, and the judge can't be the model under test."""
    try:
        judge = Judge.model_validate(_entry(document.data, "judge") or {})
    except ValidationError:
        return  # the shape check has already said what is wrong here
    try:
        ClaudeSettings.model_validate(judge.options)
    except ValidationError as error:
        yield from (_problem(details, document, _JUDGE_OPTIONS) for details in error.errors())
    if suite is None or not suite.judged:
        return
    under_test = suite.target.model
    if under_test is not None and same_model(judge.model, under_test):
        message = f"the judge can't be the model under test, {under_test!r}; name another model"
        yield _at(("judge", "model"), message, document.marks)


def _check_target(document: _Document, base_dir: Path) -> tuple[str | None, list[Problem]]:
    """The system prompt from `system_file`, if there is one, and every problem with the target.

    The prompt is read here, once, so nothing after loading touches the file system.
    """
    try:
        target = Target.model_validate(_entry(document.data, "target"))
    except ValidationError:
        return None, []  # the shape check has already said what is wrong here

    marks = document.marks
    problems: list[Problem] = []
    system = None
    if target.system_file is not None:
        try:
            system = read_text(base_dir / target.system_file)
        except UnreadableFileError as error:
            reason = f"can't read {target.system_file!r}: {error.reason}"
            problems.append(_at(("target", "system_file"), reason, marks))
    try:
        build_provider(target, base_dir)
    except UnknownNameError as error:
        problems.append(_at(("target", "provider"), str(error), marks))
    except ValidationError as error:
        problems += (_problem(details, document, _OPTIONS) for details in error.errors())
    except ProviderError as error:
        problems.append(_at(("target",), str(error), marks))
    return system, problems


def _entry(data: object, key: str) -> object:
    """`data[key]` when `data` is a mapping, or else nothing."""
    return data.get(key) if isinstance(data, dict) else None


def _entries(data: object, key: str) -> list[object]:
    """`data[key]` when that is a list, or else an empty one."""
    value = _entry(data, key)
    return value if isinstance(value, list) else []


def _with_system_prompt(suite: Suite, system: str) -> Suite:
    """The suite with its system prompt inlined, so runs never depend on the file again."""
    target = suite.target.model_copy(update={"system": system, "system_file": None})
    return suite.model_copy(update={"target": target})
