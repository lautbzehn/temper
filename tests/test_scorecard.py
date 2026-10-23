from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from rich.console import Console

from temper.comparison import compare
from temper.errors import ProviderError, RunError
from temper.pricing import cost_usd
from temper.providers import Usage
from temper.scorecard import CLIP, build_scorecard
from temper.suite import Message
from temper.summary import render_comparison
from temper.wording import dollars
from tests.support import Scripted, answer, case, judged, make_suite, run, verdict

if TYPE_CHECKING:
    from pathlib import Path

    from temper.results import Run

# Every tag a scorecard may hold. Anything else, a <script> above all, is a leak.
ALLOWED = {
    "html", "head", "meta", "title", "style", "body", "main", "header", "section", "footer",
    "h1", "h2", "h3", "p", "strong", "a", "span", "div", "table", "caption", "thead", "tbody",
    "tr", "th", "td", "details", "summary", "pre", "ul", "li",
}  # fmt: skip


class Page(HTMLParser):
    """A scorecard read back: every tag with its attributes, and all of its text."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.text = ""
        self.feed(html)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data: str) -> None:
        self.text += data

    def named(self, tag: str) -> list[dict[str, str | None]]:
        return [attributes for name, attributes in self.tags if name == tag]


def judged_run(out: Path, *, reply: str = "Sorry about that!", model: str = "fake-1") -> Run:
    suite = make_suite(judged("a", "apologizes"), case("b"), trials=2, model=model)
    answers = Scripted(
        {"a": [answer(reply, model=model)] * 2, "b": [answer(model=model), ProviderError("down")]}
    )
    judge = Scripted(
        {"a": [verdict(passed=True, reason="It apologizes."), ProviderError("judge down")]}
    )
    return run(suite, answers, out, judge=judge)


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Run:
    """One judged run, kept for the property test to rewrite."""
    return judged_run(tmp_path_factory.mktemp("template"))


def test_a_run_page_says_what_the_terminal_says(tmp_path: Path) -> None:
    finished = judged_run(tmp_path)

    page = Page(build_scorecard(finished))

    assert "2 of 2 scored trials passed (100%, likely 34 to 100%)" in page.text
    assert "1 with no verdict" in page.text
    assert "1 attempt failed, not scored" in page.text
    assert "Differences under 91 points are within noise at this size." in page.text
    assert "Sorry about that!" in page.text
    assert 'passed · judge "apologizes" · It apologizes.' in page.text
    assert 'no verdict · judge "apologizes" · no verdict: judge down' in page.text
    assert "Trial 2 · no answer, not scored · provider" in page.text
    assert "Each case's pass rate, and the range its true rate is likely in (95%)." in page.text
    assert [attributes["id"] for attributes in page.named("details")] == ["case-a", "case-b"]


def test_a_comparison_page_leads_with_the_call(tmp_path: Path) -> None:
    baseline = judged_run(tmp_path / "a")
    broken = make_suite(judged("a", "apologizes"), case("b"), trials=2, model="fake-2")
    answers = Scripted(
        {"a": [answer("No.", model="fake-2")] * 2, "b": [answer("no", model="fake-2")] * 2}
    )
    judge = Scripted({"a": [verdict(passed=False), verdict(passed=False)]})
    candidate = run(broken, answers, tmp_path / "b", judge=judge)

    page = Page(build_scorecard(candidate, baseline))

    [banner] = [
        attributes for attributes in page.named("p") if "verdict" in (attributes.get("class") or "")
    ]
    assert banner["class"] == "verdict hold"
    assert "Hold: worse overall beyond noise." in page.text
    assert "Overall 100% → 0%, -100 points (likely -100 to -18 points)." in page.text
    assert "Each case set against its twin in the baseline run" in page.text
    assert page.text.index("Candidate") < page.text.index(
        "Baseline", page.text.index("Every trial")
    )


def test_runs_of_different_cases_make_no_page(tmp_path: Path) -> None:
    other = run(make_suite(case("z")), Scripted({"z": [answer()]}), tmp_path / "z")

    with pytest.raises(RunError, match="are of different cases"):
        build_scorecard(judged_run(tmp_path / "a"), other)


def test_the_page_loads_nothing_and_says_how_to_read_it(tmp_path: Path) -> None:
    html = build_scorecard(judged_run(tmp_path))
    page = Page(html)

    assert html.startswith('<!doctype html>\n<html lang="en">')
    [policy] = [m for m in page.named("meta") if m.get("http-equiv") == "Content-Security-Policy"]
    assert policy["content"] is not None
    assert policy["content"].startswith("default-src 'none'")
    assert not re.search(r"\b(src|href)=\"(https?:|//)", html)
    bars = [span for span in page.named("span") if (span.get("class") or "").startswith("bar")]
    assert bars
    assert all(bar.get("aria-hidden") == "true" for bar in bars)
    assert all(attributes.get("scope") in {"col", "row"} for attributes in page.named("th"))
    assert page.named("caption")


def test_the_page_and_the_terminal_read_a_comparison_against_the_same_noise(
    tmp_path: Path,
) -> None:
    baseline = judged_run(tmp_path / "a")
    candidate = judged_run(tmp_path / "b", model="fake-2")
    rejudged = candidate.model_copy(
        update={"manifest": candidate.manifest.model_copy(update={"judge": "claude-opus-5-5"})}
    )
    compared = compare(baseline, rejudged)
    buffer = io.StringIO()
    render_comparison(compared, Console(file=buffer, width=200))

    page = Page(build_scorecard(rejudged, baseline))

    printed = buffer.getvalue()
    [noise] = re.findall(r"(No difference, however large,[^\n]*|Differences under [^\n]*)", printed)
    [caveat] = re.findall(r"(The runs were judged by different models[^\n]*)", printed)
    assert noise in page.text
    assert caveat in page.text
    assert [p for p in page.named("p") if p.get("class") == "caveat"]


def test_a_candidate_with_nothing_scored_gets_a_banner_that_makes_no_call(tmp_path: Path) -> None:
    baseline = judged_run(tmp_path)
    unscored = baseline.model_copy(update={"results": ()})

    page = Page(build_scorecard(unscored, baseline))

    [banner] = [p for p in page.named("p") if "verdict" in (p.get("class") or "")]
    assert banner["class"] == "verdict unmeasured"
    assert "Can't say: 2 cases with nothing scored: a (candidate), b (candidate)." in page.text
    assert "Overall" not in page.text


def test_a_long_answer_is_clipped_and_says_where_the_rest_is(tmp_path: Path) -> None:
    long = "word " * 20_000

    html = build_scorecard(judged_run(tmp_path, reply=long))

    assert len(html) < 3 * CLIP + 30_000
    assert f"… ({len(long) - CLIP:,} more characters are in results.jsonl)" in Page(html).text


text_from_a_model = st.text(st.characters(codec="utf-8"), min_size=1)


@settings(max_examples=150, deadline=None)
@given(reply=text_from_a_model, name=text_from_a_model, model=text_from_a_model)
def test_nothing_from_a_run_ever_becomes_markup(
    template: Run, reply: str, name: str, model: str
) -> None:
    results = tuple(
        result.model_copy(
            update={
                "completion": result.completion.model_copy(update={"text": reply}),
                "grades": tuple(
                    grade.model_copy(update={"check": reply, "reason": reply})
                    for grade in result.grades
                ),
                "request": result.request.model_copy(
                    update={"messages": (Message(role="user", content=reply),)}
                ),
            }
        )
        for result in template.results
    )
    failures = tuple(failure.model_copy(update={"reason": reply}) for failure in template.failures)
    manifest = template.manifest.model_copy(update={"suite": name, "model": model, "run_id": reply})
    rewritten = template.model_copy(
        update={"results": results, "failures": failures, "manifest": manifest}
    )

    page = Page(build_scorecard(rewritten))

    assert {tag for tag, _ in page.tags} <= ALLOWED
    for _, attributes in page.tags:
        assert not any(attribute.startswith("on") for attribute in attributes)
        assert (attributes.get("href") or "#case-").startswith("#case-")
        assert (attributes.get("id") or "case-").startswith("case-")
        assert re.fullmatch(
            r"(left|width):[\d.]+%(;(left|width):[\d.]+%)?", attributes.get("style") or "left:0%"
        )
    assert reply[:CLIP] in page.text
    assert name in page.text
    assert model in page.text


def test_a_flaky_paid_run_names_its_flaky_cases_and_its_cost(tmp_path: Path) -> None:
    suite = make_suite(case("a"), trials=2, model="claude-sonnet-5-5")
    usage = Usage(input_tokens=100, output_tokens=10)
    paid = [answer(text, model="claude-sonnet-5-5", usage=usage) for text in ("yes", "no")]
    finished = run(suite, Scripted({"a": paid}, charges=True), tmp_path)

    text = Page(build_scorecard(finished)).text

    assert "1 flaky case: passed some trials, failed others." in text
    each = cost_usd(usage, "claude-sonnet-5-5") or 0.0
    assert f"{dollars(2 * each)} spent" in text


def test_a_page_with_nothing_scored_says_so_instead_of_drawing_bars(tmp_path: Path) -> None:
    baseline = judged_run(tmp_path)
    unscored = baseline.model_copy(update={"results": ()})

    alone = Page(build_scorecard(unscored))

    assert "nothing scored" in alone.text
    assert "within noise" not in alone.text
