"""Labeling answers by hand, one at a time and blind to the judge: what a judge is measured against.

Nothing here reads a grade. The person sees the conversation, the answer, and
the property, and says yes or no; what the judge said stays out of sight, so
a label is a second opinion and never an echo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from temper.checks import judge_checks
from temper.labels import Label, key

if TYPE_CHECKING:
    from collections.abc import Callable

    from rich.console import Console

    from temper.labels import Labels
    from temper.results import Run, TrialResult
    from temper.suite import Suite

PROMPT = "Does the answer have this property? [y]es, [n]o, [s]kip, [q]uit: "
CHOICES = "ynsq"


@dataclass(frozen=True, slots=True)
class Labeled:
    """How a labeling session went: what there was to label, and what was labeled or skipped."""

    total: int
    labeled: int
    skipped: int

    @property
    def left(self) -> int:
        """How many judged answers still have no label."""
        return self.total - self.labeled


def label_run(
    suite: Suite, run: Run, labels: Labels, console: Console, *, ask: Callable[[str], str]
) -> Labeled:
    """Show each judged answer with no label yet, and ask for one. Quitting keeps what was given.

    `ask` puts a prompt to the person and returns what they typed, so a person
    at a terminal and a test look the same from here. Each label goes into
    `labels` the moment it's given.
    """
    judged = {
        case.id: [(index, check.property) for index, check in judge_checks(case)]
        for case in suite.cases
    }
    have = {key(label) for label in labels.read()}
    todo = [
        (result, index, property_)
        for result in run.results
        if result.status == "complete"
        for index, property_ in judged[result.case_id]
        if (result.case_id, result.trial, index) not in have
    ]
    labeled = skipped = 0
    for number, (result, index, property_) in enumerate(todo, 1):
        _show(console, result, property_, f"{number} of {len(todo)}")
        choice = _choice(ask)
        if choice == "q":
            break
        if choice == "s":
            skipped += 1
            continue
        labels.add(
            Label(
                case_id=result.case_id,
                trial=result.trial,
                check=index,
                answer=result.answer.fingerprint,
                property=property_,
                passed=choice == "y",
                at=datetime.now(UTC),
            )
        )
        labeled += 1
    return Labeled(len(todo), labeled, skipped)


def _show(console: Console, result: TrialResult, property_: str, progress: str) -> None:
    """Draw one answer to label, wrapped whatever the console's own setting.

    A console that leaves long lines for the terminal to wrap crops them
    inside a box instead, and a cropped answer can't be judged.
    """
    turns = [
        Text.assemble((f"{turn.role}: ", "bold"), turn.content) for turn in result.request.messages
    ]
    answer = Panel(Text(result.completion.text), title="answer", title_align="left")
    asked = Text.assemble(("Property: ", "bold"), property_)
    console.rule(f"{result.case_id} · trial {result.trial} · {progress}")
    console.print(Group(*turns, answer, asked), soft_wrap=False)


def _choice(ask: Callable[[str], str]) -> str:
    """One of the choices, asked for until the person gives one."""
    while True:
        said = ask(PROMPT).strip().casefold()
        if said and said[0] in CHOICES:
            return said[0]
