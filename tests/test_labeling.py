from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from rich.console import Console

from temper.errors import RunError
from temper.labeling import Labeled, label_run
from temper.labels import Label, Labels
from temper.results import RunOptions
from tests.support import Scripted, answer, case, judged, make_suite, run, verdict

if TYPE_CHECKING:
    from pathlib import Path

    from temper.providers import Completion


def session(
    out: Path,
    *typed: str,
    done: tuple[Label, ...] = (),
    second: Completion | None = None,
) -> tuple[Labels, Labeled, str]:
    """A labeling session over a two-trial judged case, answering the prompts with `typed`."""
    suite = make_suite(judged("a", "apologizes"), case("b"), trials=2)
    answers = Scripted({"a": [answer("Sorry!"), second or answer("Nope.")], "b": [answer()] * 2})
    judge = Scripted(
        {"a": [verdict(passed=True, reason="SECRET"), verdict(passed=False, reason="SECRET")]}
    )
    finished = run(suite, answers, out, RunOptions(concurrency=1), judge=judge)
    FINGERPRINTS[out / "labels.jsonl"] = finished.results[0].answer.fingerprint
    labels = Labels(out / "labels.jsonl")
    for label in done:
        labels.add(label)
    buffer = io.StringIO()
    # Set up as the command line's console is, which leaves long lines for the terminal to wrap.
    console = Console(file=buffer, width=80, soft_wrap=True)
    replies = iter(typed)
    outcome = label_run(suite, finished, labels, console, ask=lambda _: next(replies))
    return labels, outcome, buffer.getvalue()


FINGERPRINTS: dict[Path, str] = {}


def finished_answer(labels: Labels) -> str:
    """The fingerprint of the first answer labeled in a session."""
    return FINGERPRINTS[labels.path]


def given(trial: int, *, passed: bool) -> Label:
    at = datetime(2026, 10, 22, tzinfo=UTC)
    return Label(
        case_id="a",
        trial=trial,
        check=0,
        answer="0" * 16,
        property="apologizes",
        passed=passed,
        at=at,
    )


def test_each_judged_answer_is_shown_and_its_label_kept(tmp_path: Path) -> None:
    labels, outcome, shown = session(tmp_path, "y", "n")

    assert outcome == Labeled(total=2, labeled=2, skipped=0)
    assert outcome.left == 0
    assert [(label.trial, label.passed) for label in labels.read()] == [(1, True), (2, False)]
    assert labels.read()[0].property == "apologizes"
    assert labels.read()[0].answer == finished_answer(labels)
    assert "a · trial 1 · 1 of 2" in shown
    assert "user: A question for a" in shown
    assert "Sorry!" in shown
    assert "Property: apologizes" in shown


def test_a_long_answer_is_shown_whole_however_narrow_the_terminal(tmp_path: Path) -> None:
    words = [f"word{n}" for n in range(60)]

    _, _, shown = session(tmp_path, "y", "y", second=answer(" ".join(words)))

    assert all(word in shown for word in words)


def test_the_person_never_sees_what_the_judge_said(tmp_path: Path) -> None:
    _, _, shown = session(tmp_path, "y", "n")

    assert "SECRET" not in shown
    assert "verdict" not in shown


def test_skipping_and_quitting_keep_what_was_given(tmp_path: Path) -> None:
    labels, outcome, _ = session(tmp_path, "s", "q")

    assert outcome == Labeled(total=2, labeled=0, skipped=1)
    assert outcome.left == 2
    assert labels.read() == []


def test_anything_else_is_asked_again(tmp_path: Path) -> None:
    labels, outcome, _ = session(tmp_path, "maybe", "", " Yes please", "No")

    assert outcome.labeled == 2
    assert [label.passed for label in labels.read()] == [True, False]


def test_answers_already_labeled_are_not_asked_again(tmp_path: Path) -> None:
    labels, outcome, shown = session(tmp_path, "n", done=(given(1, passed=True),))

    assert outcome == Labeled(total=1, labeled=1, skipped=0)
    assert "a · trial 2 · 1 of 1" in shown
    assert [label.trial for label in labels.read()] == [1, 2]


def test_only_complete_answers_are_labeled(tmp_path: Path) -> None:
    _, outcome, _ = session(tmp_path, "y", second=answer("Nope", status="truncated"))

    assert outcome.total == 1


def test_labels_read_back_and_a_bad_file_says_so(tmp_path: Path) -> None:
    labels = Labels.of(tmp_path)

    assert labels.path == tmp_path / "labels.jsonl"
    assert labels.read() == []

    labels.add(given(1, passed=True))
    assert labels.read() == [given(1, passed=True)]

    labels.path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RunError, match=r"line 1 of .*labels\.jsonl.* isn't a label"):
        labels.read()
    with pytest.raises(RunError, match="can't read labels"):
        Labels(tmp_path).read()
