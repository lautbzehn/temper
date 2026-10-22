from __future__ import annotations

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from temper.errors import UnknownNameError
from temper.graders import Contains, Equals, NotContains, build_grader, normalize
from temper.suite import Check

words = st.text(alphabet=string.ascii_letters, min_size=1)
some_text = st.text().filter(str.strip)
plain_words = st.text(
    alphabet=string.ascii_letters + string.digits + string.punctuation, min_size=1
)
spacing = st.text(alphabet=" \t\n", min_size=1)


@pytest.mark.parametrize(
    ("grader", "answer", "passed", "reason"),
    [
        (Contains(text="4471"), "Order #4471 ships Thursday.", True, 'says "4471"'),
        (Contains(text="sorry"), "Please calm down.", False, 'never says "sorry"'),
        (NotContains(text="calm down"), "I'm so sorry.", True, 'avoids "calm down"'),
        (NotContains(text="calm down"), "Please CALM  down.", False, 'says "calm down"'),
        (Equals(text="Yes"), "  yes ", True, "matches"),
        (Equals(text="Yes"), "Yes, of course", False, "says something else"),
    ],
)
def test_graders_explain_their_verdict(
    grader: Contains | NotContains | Equals, answer: str, *, passed: bool, reason: str
) -> None:
    grade = grader.grade(answer)

    assert (grade.passed, grade.reason) == (passed, reason)


def test_a_grade_names_its_check() -> None:
    assert Contains(text="refund").grade("").check == 'contains "refund"'


def test_case_can_be_made_to_count() -> None:
    assert not Contains(text="Scranton", case_sensitive=True).grade("scranton").passed
    assert Contains(text="Scranton").grade("scranton").passed


def test_blank_text_is_refused() -> None:
    with pytest.raises(ValidationError, match="can't be blank"):
        Contains(text="   ")


def test_build_grader_suggests_a_near_name() -> None:
    with pytest.raises(UnknownNameError, match=r"did you mean 'not_contains'\?"):
        build_grader(Check.model_validate({"type": "not_contain", "text": "x"}))


def test_build_grader_lists_the_choices_when_nothing_is_close() -> None:
    with pytest.raises(UnknownNameError, match="choose from contains, equals, not_contains"):
        build_grader(Check.model_validate({"type": "sentiment"}))


def test_build_grader_validates_settings() -> None:
    with pytest.raises(ValidationError):
        build_grader(Check.model_validate({"type": "contains", "text": "x", "loudly": True}))


@given(st.text())
def test_normalizing_twice_changes_nothing(text: str) -> None:
    assert normalize(normalize(text)) == normalize(text)


@given(prefix=st.text(), text=some_text, suffix=st.text())
def test_contains_finds_text_wherever_it_sits(prefix: str, text: str, suffix: str) -> None:
    assert Contains(text=text).grade(prefix + text + suffix).passed


@given(answer=st.lists(plain_words, min_size=1), text=plain_words, gaps=st.data())
def test_respacing_or_recasing_an_answer_never_changes_a_verdict(
    answer: list[str], text: str, gaps: st.DataObject
) -> None:
    plain = " ".join(answer)
    reworked = "".join(word.swapcase() + gaps.draw(spacing) for word in answer)

    for grader in (Contains(text=text), NotContains(text=text), Equals(text=text)):
        assert grader.grade(reworked).passed == grader.grade(plain).passed


@given(st.lists(words, min_size=1))
def test_equals_ignores_case_and_spacing(parts: list[str]) -> None:
    text = " ".join(parts)
    answer = "\n  " + "   ".join(part.swapcase() for part in parts) + "\t"

    assert Equals(text=text).grade(answer).passed
