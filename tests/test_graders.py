from __future__ import annotations

import json
import re
import string

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from temper.checks import build_check, check_kinds, judge_checks
from temper.errors import UnknownNameError
from temper.graders import (
    Contains,
    Cost,
    Equals,
    Grader,
    Json,
    JudgeCheck,
    Latency,
    Length,
    Matches,
    NotContains,
    normalize,
)
from temper.suite import Case, Check
from tests.support import seen

words = st.text(alphabet=string.ascii_letters, min_size=1)
some_text = st.text().filter(str.strip)
plain_words = st.text(
    alphabet=string.ascii_letters + string.digits + string.punctuation, min_size=1
)
spacing = st.text(alphabet=" \t\n", min_size=1)
json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda inner: st.lists(inner) | st.dictionaries(st.text(), inner),
    max_leaves=20,
)


@pytest.mark.parametrize(
    ("grader", "answer", "passed", "reason"),
    [
        (Contains(text="4471"), "Order #4471 ships Thursday.", True, 'says "4471"'),
        (Contains(text="sorry"), "Please calm down.", False, 'never says "sorry"'),
        (NotContains(text="calm down"), "I'm so sorry.", True, 'avoids "calm down"'),
        (NotContains(text="calm down"), "Please CALM  down.", False, 'says "calm down"'),
        (Equals(text="Yes"), "  yes ", True, "matches"),
        (Equals(text="Yes"), "Yes, of course", False, "says something else"),
        (Matches(pattern=r"#\d{4}"), "Order #4471 ships Thursday.", True, 'matches at "#4471"'),
        (Matches(pattern=r"#\d{4}"), "Order 4471 ships Thursday.", False, "never matches"),
        (Length(max_words=3), "one two three", True, "3 words"),
        (Length(max_words=3), "one two three four", False, "4 words"),
        (Length(min_words=2), "one", False, "1 word"),
        (Length(min_words=1, max_words=2), "one two", True, "2 words"),
        (Json(), '{"name": "Pam"}', True, "is JSON"),
        (Json(), "Sure! {", False, "isn't JSON: Expecting value at line 1, column 1"),
        (Json(keys=("name", "email")), '{"name": "Pam"}', False, "lacks email"),
        (Json(keys=("name",)), '{"name": "Pam"}', True, "has every key"),
        (Json(keys=("name",)), "[1, 2]", False, "is JSON, but not an object"),
        (Json(), "NaN", False, "isn't JSON: NaN isn't JSON"),
        (Json(), "[1, -Infinity]", False, "isn't JSON: -Infinity isn't JSON"),
        (Cost(max_usd=0.01), "anything", True, "cost $0.0010"),
        (Cost(max_usd=0.0005), "anything", False, "cost $0.0010"),
        (Latency(max_s=1), "anything", True, "answered in 0.1 s"),
    ],
)
def test_graders_explain_their_verdict(
    grader: Grader, answer: str, *, passed: bool, reason: str
) -> None:
    grade = grader.grade(seen(answer))

    assert (grade.passed, grade.reason) == (passed, reason)


def test_a_slow_answer_fails_a_latency_check() -> None:
    grade = Latency(max_s=2).grade(seen("", latency_ms=2_500))

    assert (grade.passed, grade.reason) == (False, "answered in 2.5 s")


def test_an_unpriced_answer_gets_no_cost_verdict() -> None:
    grade = Cost(max_usd=0.01).grade(seen("", cost_usd=None))

    assert grade.passed is None
    assert grade.reason == "this model has no list price, so the cost isn't known"


@pytest.mark.parametrize(
    ("grader", "check"),
    [
        (Contains(text="refund"), 'contains "refund"'),
        (Matches(pattern=r"\d+"), r"matches /\d+/"),
        (Length(max_words=5), "length at most 5 words"),
        (Length(min_words=5), "length at least 5 words"),
        (Length(min_words=1, max_words=5), "length 1 to 5 words"),
        (Json(), "json"),
        (Json(keys=("a", "b")), "json with a, b"),
        (Cost(max_usd=0.01), "cost at most $0.0100"),
        (Latency(max_s=2), "latency at most 2 s"),
    ],
)
def test_a_grade_names_its_check(grader: Grader, check: str) -> None:
    assert grader.grade(seen("{}")).check == check


def test_case_can_be_made_to_count() -> None:
    assert not Contains(text="Scranton", case_sensitive=True).grade(seen("scranton")).passed
    assert Contains(text="Scranton").grade(seen("scranton")).passed


@pytest.mark.parametrize(
    ("settings", "complaint"),
    [
        ({"type": "contains", "text": "   "}, "can't be blank"),
        ({"type": "matches", "pattern": "("}, "isn't a regular expression"),
        ({"type": "length"}, "give min_words, max_words, or both"),
        ({"type": "length", "min_words": 5, "max_words": 2}, "can't be more than max_words"),
        ({"type": "length", "max_words": 0}, "greater than 0"),
        ({"type": "length", "min_words": -1}, "greater than or equal to 0"),
        ({"type": "cost", "max_usd": 0}, "greater than 0"),
        ({"type": "latency", "max_s": -1}, "greater than 0"),
        ({"type": "judge", "property": "  "}, "can't be blank"),
        ({"type": "judge"}, "required"),
        ({"type": "contains", "text": "x", "loudly": True}, "extra"),
    ],
)
def test_bad_settings_are_refused(settings: dict[str, object], complaint: str) -> None:
    with pytest.raises(ValidationError, match=complaint):
        build_check(Check.model_validate(settings))


def test_build_check_suggests_a_near_name() -> None:
    with pytest.raises(UnknownNameError, match=r"did you mean 'not_contains'\?"):
        build_check(Check.model_validate({"type": "not_contain", "text": "x"}))


def test_build_check_lists_the_choices_when_nothing_is_close() -> None:
    choices = "contains, cost, equals, json, judge, latency, length, matches, not_contains"
    with pytest.raises(UnknownNameError, match=f"choose from {choices}"):
        build_check(Check.model_validate({"type": "sentiment"}))


def test_the_judge_is_a_kind_of_check_but_not_a_grader() -> None:
    built = build_check(Check.model_validate({"type": "judge", "property": "is kind"}))

    assert isinstance(built, JudgeCheck)
    assert check_kinds()["judge"] is JudgeCheck
    assert not issubclass(JudgeCheck, Grader)


def test_judge_checks_come_with_their_positions() -> None:
    checks = [
        {"type": "contains", "text": "x"},
        {"type": "judge", "property": "p"},
        {"type": "judge", "property": "q"},
    ]
    case = Case.model_validate({"id": "a", "input": "?", "checks": checks})

    assert [(index, check.property) for index, check in judge_checks(case)] == [(1, "p"), (2, "q")]
    assert case.judged == (1, 2)


@given(st.text())
def test_normalizing_twice_changes_nothing(text: str) -> None:
    assert normalize(normalize(text)) == normalize(text)


@given(prefix=st.text(), text=some_text, suffix=st.text())
def test_contains_finds_text_wherever_it_sits(prefix: str, text: str, suffix: str) -> None:
    assert Contains(text=text).grade(seen(prefix + text + suffix)).passed


@given(answer=st.lists(plain_words, min_size=1), text=plain_words, gaps=st.data())
def test_respacing_or_recasing_an_answer_never_changes_a_verdict(
    answer: list[str], text: str, gaps: st.DataObject
) -> None:
    plain = " ".join(answer)
    reworked = "".join(word.swapcase() + gaps.draw(spacing) for word in answer)

    for grader in (Contains(text=text), NotContains(text=text), Equals(text=text)):
        assert grader.grade(seen(reworked)).passed == grader.grade(seen(plain)).passed


@given(st.lists(words, min_size=1))
def test_equals_ignores_case_and_spacing(parts: list[str]) -> None:
    text = " ".join(parts)
    answer = "\n  " + "   ".join(part.swapcase() for part in parts) + "\t"

    assert Equals(text=text).grade(seen(answer)).passed


@given(text=plain_words, answer=st.text())
def test_matching_escaped_text_is_a_case_sensitive_search(text: str, answer: str) -> None:
    assert Matches(pattern=re.escape(text)).grade(seen(answer)).passed == (text in answer)


@given(parts=st.lists(plain_words, min_size=1), gaps=st.data())
def test_length_counts_words_however_they_are_spaced(parts: list[str], gaps: st.DataObject) -> None:
    answer = gaps.draw(spacing) + "".join(part + gaps.draw(spacing) for part in parts)

    assert Length(min_words=len(parts), max_words=len(parts)).grade(seen(answer)).passed


@given(json_values)
def test_anything_json_can_write_is_json(value: object) -> None:
    assert Json().grade(seen(json.dumps(value))).passed
