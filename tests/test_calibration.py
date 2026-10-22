from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from rich.console import Console

from temper.calibration import FLOOR, KAPPA, TRUSTED, Calibration, Disagreement, calibrate
from temper.labels import Label
from temper.results import RunOptions
from temper.summary import render_calibration
from tests.support import Scripted, answer, judged, make_suite, run, verdict

if TYPE_CHECKING:
    from pathlib import Path

    from temper.results import Run, TrialResult
    from temper.suite import Suite

counts = st.integers(min_value=0, max_value=50)


def trial(run: Run, case_id: str, number: int) -> TrialResult:
    return next(r for r in run.results if (r.case_id, r.trial) == (case_id, number))


def label(
    result: TrialResult,
    *,
    passed: bool,
    check: int = 0,
    property_: str = "apologizes",
    answer: str | None = None,
) -> Label:
    """A label about `result`'s answer, unless `answer` names a different one."""
    return Label(
        case_id=result.case_id,
        trial=result.trial,
        check=check,
        answer=answer or result.answer.fingerprint,
        property=property_,
        passed=passed,
        at=datetime(2026, 10, 22, tzinfo=UTC),
    )


def tallied(both_passed: int, judge_only: int, person_only: int, both_failed: int) -> Calibration:
    return Calibration(
        both_passed=both_passed,
        judge_only=judge_only,
        person_only=person_only,
        both_failed=both_failed,
        without_verdict=0,
        unmatched=0,
        reworded=0,
        by_property={},
        disagreements=(),
    )


def judged_run(out: Path) -> tuple[Suite, Run]:
    suite = make_suite(judged("a", "apologizes"), judged("b", "is brief"), trials=2)
    answers = Scripted({"a": [answer("Sorry"), answer("Sorry again")], "b": [answer()] * 2})
    judge = Scripted(
        {
            "a": [verdict(passed=True), verdict(passed=False, reason="No apology.")],
            "b": [verdict(passed=True), verdict(passed=True)],
        }
    )
    return suite, run(suite, answers, out, RunOptions(concurrency=1), judge=judge)


def test_every_label_is_set_against_the_judges_verdict(tmp_path: Path) -> None:
    suite, finished = judged_run(tmp_path)
    labels = [
        label(trial(finished, "a", 1), passed=True),
        label(trial(finished, "a", 2), passed=True),
        label(trial(finished, "b", 1), passed=False, property_="is brief"),
        label(trial(finished, "b", 2), passed=True, property_="is brief"),
    ]

    result = calibrate(suite, finished, labels)

    assert (result.labeled, result.agreed, result.agreement) == (4, 2, 0.5)
    assert (result.both_passed, result.judge_only, result.person_only, result.both_failed) == (
        2,
        1,
        1,
        0,
    )
    assert result.kappa == pytest.approx(-1 / 3)
    assert result.by_property == {"apologizes": (1, 2), "is brief": (1, 2)}
    assert result.disagreements == (
        Disagreement(
            "a", 2, "apologizes", judge_passed=False, judge_reason="No apology.", label_passed=True
        ),
        Disagreement(
            "b", 1, "is brief", judge_passed=True, judge_reason="because", label_passed=False
        ),
    )
    assert result.trusted is None


def test_labels_without_a_verdict_or_about_other_answers_are_counted_apart(
    tmp_path: Path,
) -> None:
    suite = make_suite(judged("a"), trials=2)
    judge = Scripted({"a": [answer("not a verdict"), verdict(passed=True)]})
    answers = Scripted({"a": [answer(), answer("another")]})
    finished = run(suite, answers, tmp_path, RunOptions(concurrency=1), judge=judge)
    labels = [
        label(trial(finished, "a", 1), passed=True),
        label(trial(finished, "a", 2), passed=True, answer="0" * 16),
        label(trial(finished, "a", 2), passed=True, check=5, property_="unknown"),
    ]

    result = calibrate(suite, finished, labels)

    assert (result.labeled, result.without_verdict, result.unmatched) == (0, 1, 2)
    assert (result.agreement, result.kappa, result.trusted) == (None, None, None)


def test_a_label_finds_its_property_by_wording_when_checks_are_reordered(tmp_path: Path) -> None:
    checks = [
        {"type": "judge", "property": "apologizes"},
        {"type": "judge", "property": "is brief"},
    ]
    first = make_suite({"id": "a", "input": "Hi", "checks": checks})
    earlier = run(
        first,
        Scripted({"a": [answer()]}),
        tmp_path,
        judge=Scripted({"a": [verdict(passed=True), verdict(passed=False)]}),
    )
    labeled = label(trial(earlier, "a", 1), passed=True, check=0)

    swapped = make_suite({"id": "a", "input": "Hi", "checks": list(reversed(checks))})
    later = run(
        swapped,
        Scripted({"a": [answer()]}),
        tmp_path,
        judge=Scripted({"a": [verdict(passed=False), verdict(passed=True)]}),
    )
    result = calibrate(swapped, later, [labeled])

    assert result.by_property == {"is brief": (0, 0), "apologizes": (1, 1)}
    assert (result.reworded, result.disagreements) == (0, ())


def test_a_reworded_property_keeps_its_labels_by_position_and_says_so(tmp_path: Path) -> None:
    _, finished = judged_run(tmp_path)
    reworded = make_suite(judged("a", "says sorry"), judged("b", "is brief"), trials=2)

    result = calibrate(reworded, finished, [label(trial(finished, "a", 1), passed=True)])

    assert result.by_property == {"says sorry": (1, 1), "is brief": (0, 0)}
    assert result.reworded == 1


def test_trust_takes_enough_labels_agreement_and_kappa() -> None:
    assert tallied(3, 0, 0, 0).trusted is None
    assert tallied(FLOOR, 0, 0, 0).trusted is False
    assert tallied(15, 0, 0, 5).trusted is True
    assert tallied(18, 1, 1, 0).trusted is False


def test_kappa_is_undefined_when_everyone_always_says_the_same_thing() -> None:
    always_yes = tallied(3, 0, 0, 0)

    assert (always_yes.agreement, always_yes.kappa) == (1.0, None)


@given(both_passed=counts, judge_only=counts, person_only=counts, both_failed=counts)
def test_agreement_is_a_share_and_kappa_never_passes_one(
    both_passed: int, judge_only: int, person_only: int, both_failed: int
) -> None:
    assume(both_passed + judge_only + person_only + both_failed > 0)

    result = tallied(both_passed, judge_only, person_only, both_failed)

    assert result.agreement is not None
    assert 0 <= result.agreement <= 1
    if result.kappa is not None:
        assert result.kappa <= 1 + 1e-9
    if judge_only == person_only == 0 and both_passed and both_failed:
        assert result.kappa == pytest.approx(1.0)
    if result.labeled < FLOOR:
        assert result.trusted is None
    else:
        earned = result.agreement >= TRUSTED and (result.kappa or 0) >= KAPPA
        assert result.trusted == earned


def test_the_report_says_when_no_label_met_a_verdict(tmp_path: Path) -> None:
    suite = make_suite(judged("a"))
    judge = Scripted({"a": [answer("not a verdict")]})
    finished = run(suite, Scripted({"a": [answer()]}), tmp_path, judge=judge)
    buffer = io.StringIO()

    render_calibration(
        suite,
        calibrate(suite, finished, [label(trial(finished, "a", 1), passed=True)]),
        Console(file=buffer),
    )

    assert "No label met a verdict · 1 with no verdict" in buffer.getvalue()


def test_the_report_says_when_the_judge_earned_trust() -> None:
    suite = make_suite(judged("a"))
    earned = tallied(15, 0, 0, 5)
    buffer = io.StringIO()

    render_calibration(suite, earned, Console(file=buffer, width=120))

    assert "Agreement 100% (20 of 20) · kappa 1.00" in buffer.getvalue()
    assert "Trusted: 20 labels or more" in buffer.getvalue()


def test_the_report_says_what_trust_still_takes() -> None:
    suite = make_suite(judged("a"))
    short = tallied(18, 1, 1, 0)
    buffer = io.StringIO()

    render_calibration(suite, short, Console(file=buffer, width=200))

    assert "Agreement 90% (18 of 20) · kappa -0.05" in buffer.getvalue()
    assert "Not yet trusted: it takes agreement at 90% or better and kappa at 0.6 or better." in (
        buffer.getvalue()
    )
