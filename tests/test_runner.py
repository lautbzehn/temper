from __future__ import annotations

import asyncio
import re

import pytest

from temper.errors import ProviderError
from temper.providers import FakeProvider
from temper.runner import run_suite
from tests.support import Slow, case, make_suite


def test_results_come_back_in_suite_order_whatever_order_they_finish() -> None:
    provider = Slow()
    suite = make_suite(case("first"), case("second"), trials=2)

    run = asyncio.run(run_suite(suite, provider))

    in_suite_order = [("first", 1), ("first", 2), ("second", 1), ("second", 2)]
    assert provider.seen == in_suite_order[::-1]
    assert [(r.case_id, r.trial) for r in run.results] == in_suite_order


def test_no_more_than_the_concurrency_limit_wait_at_once() -> None:
    provider = Slow()
    suite = make_suite(*(case(f"case-{n}") for n in range(6)), trials=2)

    asyncio.run(run_suite(suite, provider, concurrency=3))

    assert provider.most_in_flight == 3


def test_each_answer_is_graded_by_every_check() -> None:
    suite = make_suite(
        case(
            "complaint",
            {"type": "contains", "text": "sorry"},
            {"type": "not_contains", "text": "calm down"},
        )
    )
    provider = FakeProvider({"complaint": ["Sorry! Please calm down."]})

    [result] = asyncio.run(run_suite(suite, provider)).results

    assert [grade.passed for grade in result.grades] == [True, False]
    assert not result.passed
    assert result.answer == "Sorry! Please calm down."
    assert result.model == "fake"


def test_trials_default_to_the_suite_and_can_be_overridden() -> None:
    suite = make_suite(case("only"), trials=3)
    provider = FakeProvider({"only": ["yes"]})

    assert len(asyncio.run(run_suite(suite, provider)).results) == 3
    assert len(asyncio.run(run_suite(suite, provider, trials=5)).results) == 5


def test_the_manifest_records_what_ran() -> None:
    suite = make_suite(case("a"), case("b"), trials=2, name="paper-sales")

    manifest = asyncio.run(run_suite(suite, FakeProvider({"a": ["yes"], "b": ["no"]}))).manifest

    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", manifest.run_id)
    assert (manifest.suite, manifest.provider, manifest.model) == ("paper-sales", "fake", "fake-1")
    assert (manifest.cases, manifest.trials) == (2, 2)
    assert manifest.started_at <= manifest.finished_at


def test_the_fingerprint_changes_with_the_suite_and_only_then() -> None:
    def fingerprint(*texts: str) -> str:
        suite = make_suite(*(case(text) for text in texts))
        provider = FakeProvider({text: ["yes"] for text in texts})
        return asyncio.run(run_suite(suite, provider)).manifest.fingerprint

    assert fingerprint("a") == fingerprint("a")
    assert fingerprint("a") != fingerprint("b")


@pytest.mark.parametrize(("trials", "concurrency"), [(0, 1), (1, 0)])
def test_trials_and_concurrency_must_be_positive(trials: int, concurrency: int) -> None:
    suite = make_suite(case("only"))

    with pytest.raises(ValueError, match="at least 1"):
        asyncio.run(run_suite(suite, Slow(), trials=trials, concurrency=concurrency))


def test_a_provider_failure_stops_the_run() -> None:
    suite = make_suite(case("answered"), case("unanswered"))

    with pytest.RaisesGroup(pytest.RaisesExc(ProviderError, match="unanswered")):
        asyncio.run(run_suite(suite, FakeProvider({"answered": ["yes"]})))
