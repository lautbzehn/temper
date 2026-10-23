from __future__ import annotations

import io
import re
from typing import TYPE_CHECKING

import pytest
from rich.console import Console

from temper.comparison import compare
from temper.errors import RunError
from temper.providers import FakeProvider
from temper.runner import cases_fingerprint
from temper.summary import render_comparison
from tests.support import case, make_suite, run

if TYPE_CHECKING:
    from pathlib import Path

    from temper.results import Run

CASES = (case("steady"), case("broken"), case("wobbly"), case("fixed"))


def scripted(out: Path, replies: dict[str, list[str]], *, model: str = "fake-1") -> Run:
    """A three-trial run of the four cases, answering each from `replies`."""
    suite = make_suite(*CASES, trials=3, model=model)
    return run(suite, FakeProvider(replies), out)


def before_and_after(out: Path) -> tuple[Run, Run]:
    baseline = scripted(
        out / "a",
        {"steady": ["yes"], "broken": ["yes"], "wobbly": ["yes", "no", "yes"], "fixed": ["no"]},
    )
    candidate = scripted(
        out / "b",
        {"steady": ["yes"], "broken": ["no"], "wobbly": ["no", "yes", "no"], "fixed": ["yes"]},
        model="fake-2",
    )
    return baseline, candidate


def test_each_case_is_set_against_its_twin(tmp_path: Path) -> None:
    baseline, candidate = before_and_after(tmp_path)

    compared = compare(baseline, candidate)

    changes = {change.case_id: change.difference for change in compared.changes}
    assert [change.case_id for change in compared.changes] == [
        "steady",
        "broken",
        "wobbly",
        "fixed",
    ]
    assert changes["steady"].value == 0
    assert changes["broken"].direction == "worse"
    assert changes["wobbly"].direction is None
    assert changes["fixed"].direction == "better"
    assert [change.case_id for change in compared.regressed] == ["broken"]
    assert [change.case_id for change in compared.improved] == ["fixed"]
    assert compared.overall.baseline.passed == 8
    assert compared.overall.candidate.passed == 7
    assert baseline.flaky == ("wobbly",)


def test_one_broken_case_holds_the_candidate_whatever_the_average_says(tmp_path: Path) -> None:
    baseline, candidate = before_and_after(tmp_path)

    compared = compare(baseline, candidate)

    assert compared.finding == "worse"
    assert not compared.ship


def test_a_candidate_ships_when_nothing_got_worse_beyond_noise(tmp_path: Path) -> None:
    baseline = scripted(
        tmp_path / "a", {name: ["yes"] for name in ("steady", "broken", "wobbly", "fixed")}
    )
    candidate = scripted(
        tmp_path / "b",
        {
            **{name: ["yes"] for name in ("steady", "broken", "fixed")},
            "wobbly": ["no", "yes", "yes"],
        },
    )

    compared = compare(baseline, candidate)

    assert compared.finding == "undecided"
    assert compared.ship
    assert compared.regressed == ()
    assert compared.trials_to_tell is not None
    assert compared.trials_to_tell > 3


def test_a_clear_improvement_is_called_better(tmp_path: Path) -> None:
    baseline = scripted(
        tmp_path / "a", {name: ["no"] for name in ("steady", "broken", "wobbly", "fixed")}
    )
    candidate = scripted(
        tmp_path / "b", {name: ["yes"] for name in ("steady", "broken", "wobbly", "fixed")}
    )

    compared = compare(baseline, candidate)

    assert compared.finding == "better"
    assert compared.ship
    assert compared.overall.value == 1.0
    assert len(compared.improved) == 4
    assert compared.trials_to_tell is None or compared.trials_to_tell >= 1


def test_runs_of_different_cases_cannot_be_compared(tmp_path: Path) -> None:
    baseline = scripted(
        tmp_path / "a", {name: ["yes"] for name in ("steady", "broken", "wobbly", "fixed")}
    )
    other = run(
        make_suite(case("steady"), trials=3), FakeProvider({"steady": ["yes"]}), tmp_path / "c"
    )

    with pytest.raises(RunError, match="are of different cases"):
        compare(baseline, other)


def test_a_run_from_before_comparing_says_so(tmp_path: Path) -> None:
    baseline, candidate = before_and_after(tmp_path)
    old = baseline.model_copy(
        update={"manifest": baseline.manifest.model_copy(update={"cases_fingerprint": None})}
    )

    with pytest.raises(RunError, match="was kept before runs could be compared"):
        compare(old, candidate)


def test_the_report_names_the_broken_case_and_holds(tmp_path: Path) -> None:
    baseline, candidate = before_and_after(tmp_path)
    buffer = io.StringIO()

    render_comparison(compare(baseline, candidate), Console(file=buffer, width=200))

    shown = buffer.getvalue()
    assert "test · 4 cases" in shown
    assert "baseline  " in shown
    assert "fake fake-2 · 4 cases × 3 trials" in shown
    assert re.search(r"broken\s+3/3\s+0/3\s+-100 points, worse beyond noise", shown)
    assert re.search(r"fixed\s+0/3\s+3/3\s+\+100 points, better beyond noise", shown)
    assert re.search(r"steady\s+3/3\s+3/3\s+\+0 points", shown)
    assert "Overall 67% → 58%, -8 points (likely" in shown
    assert "Differences under" in shown
    assert "Hold: 1 case got worse beyond noise: broken." in shown


def test_the_report_says_what_would_settle_an_undecided_change(tmp_path: Path) -> None:
    baseline = scripted(
        tmp_path / "a", {name: ["yes"] for name in ("steady", "broken", "wobbly", "fixed")}
    )
    candidate = scripted(
        tmp_path / "b",
        {
            **{name: ["yes"] for name in ("steady", "broken", "fixed")},
            "wobbly": ["no", "yes", "yes"],
        },
    )
    buffer = io.StringIO()

    render_comparison(compare(baseline, candidate), Console(file=buffer, width=200))

    shown = buffer.getvalue()
    assert (
        "Ship: nothing got worse beyond noise. The overall change is within noise at this size;"
        in shown
    )
    assert "14 trials per case would tell 8 points from noise." in shown


def test_a_candidate_with_nothing_scored_gets_no_call(tmp_path: Path) -> None:
    suite = make_suite(case("a"), trials=1)
    baseline = run(suite, FakeProvider({"a": ["yes"]}), tmp_path / "a")
    unscored = baseline.model_copy(update={"results": ()})
    buffer = io.StringIO()

    compared = compare(baseline, unscored)
    render_comparison(compared, Console(file=buffer, width=200))

    assert compared.finding == "unmeasured"
    assert not compared.ship
    assert compared.trials_to_tell is None
    assert "nothing scored" in buffer.getvalue()
    assert "Overall" not in buffer.getvalue()
    assert "Can't say: 1 case with nothing scored: a (candidate)." in buffer.getvalue()


def test_runs_judged_by_different_models_say_so_first(tmp_path: Path) -> None:
    baseline, candidate = before_and_after(tmp_path)
    rejudged = candidate.model_copy(
        update={"manifest": candidate.manifest.model_copy(update={"judge": "claude-opus-5-5"})}
    )
    buffer = io.StringIO()

    compared = compare(baseline, rejudged)
    render_comparison(compared, Console(file=buffer, width=200))

    assert compared.judges_differ
    assert not compare(baseline, candidate).judges_differ
    assert (
        "The runs were judged by different models, no judge and claude-opus-5-5, so a change "
        "may be the judge's and not the target's."
    ) in buffer.getvalue()


def test_tags_do_not_change_which_cases_these_are() -> None:
    plain = make_suite(case("a"))
    tagged = make_suite({**case("a"), "tags": ["orders"]})
    asked_differently = make_suite({**case("a"), "input": "Something else"})

    assert cases_fingerprint(plain) == cases_fingerprint(tagged)
    assert cases_fingerprint(plain) != cases_fingerprint(asked_differently)


def many(out: Path, passes: int, *, model: str = "fake-1") -> Run:
    """A thirty-case, three-trial run where every case passes `passes` of its trials."""
    cases = [case(f"c{n:02d}") for n in range(30)]
    replies = {c["id"]: ["yes"] * passes + ["no"] * (3 - passes) for c in cases}
    return run(make_suite(*cases, trials=3, model=model), FakeProvider(replies), out)


def test_a_drift_no_single_case_shows_still_decides_on_the_whole(tmp_path: Path) -> None:
    steady = many(tmp_path / "a", 3)
    slipped = many(tmp_path / "b", 2, model="fake-2")

    down = compare(steady, slipped)
    up = compare(slipped, steady)

    assert down.regressed == ()
    assert (down.finding, down.ship) == ("worse", False)
    assert up.improved == ()
    assert (up.finding, up.ship) == ("better", True)
    calls = (
        (down, "Hold: worse overall beyond noise."),
        (up, "Ship: better overall beyond noise."),
    )
    for compared, call in calls:
        buffer = io.StringIO()
        render_comparison(compared, Console(file=buffer, width=200))
        assert call in buffer.getvalue()
