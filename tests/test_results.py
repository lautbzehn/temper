from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from temper.providers import FakeProvider
from temper.results import Manifest, Run, TrialResult, write_run
from temper.runner import run_suite
from tests.support import case, make_suite

if TYPE_CHECKING:
    from pathlib import Path


def sample_run() -> Run:
    suite = make_suite(case("steady"), case("wobbly"), trials=2)
    provider = FakeProvider({"steady": ["yes"], "wobbly": ["yes", "no"]})
    return asyncio.run(run_suite(suite, provider))


def test_trials_group_by_case_in_suite_order() -> None:
    grouped = sample_run().by_case()

    assert list(grouped) == ["steady", "wobbly"]
    assert [[r.passed for r in results] for results in grouped.values()] == [
        [True, True],
        [True, False],
    ]


def test_a_run_counts_the_trials_that_passed() -> None:
    assert sample_run().trials_passed == 3


def test_a_written_run_reads_back_the_same(tmp_path: Path) -> None:
    run = sample_run()

    folder = write_run(run, tmp_path)

    assert folder == tmp_path / run.manifest.run_id
    manifest = Manifest.model_validate_json((folder / "manifest.json").read_text(encoding="utf-8"))
    lines = (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert manifest == run.manifest
    assert tuple(TrialResult.model_validate_json(line) for line in lines) == run.results


def test_each_result_line_is_plain_json(tmp_path: Path) -> None:
    folder = write_run(sample_run(), tmp_path)

    first = json.loads((folder / "results.jsonl").read_text(encoding="utf-8").splitlines()[0])

    assert first["case_id"] == "steady"
    assert first["grades"] == [{"check": 'contains "yes"', "passed": True, "reason": 'says "yes"'}]
