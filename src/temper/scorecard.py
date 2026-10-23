"""The scorecard: one HTML file that says what a run found, to read, share, or keep.

It loads nothing and runs nothing: no scripts, no fonts, no network, and a
content policy that forbids them even if something slipped through. Every
word from a run is escaped by `markup`, and every long text is clipped, so
a model's output can neither break the page nor bloat it. The same run
always makes the same page, byte for byte, so a scorecard can be checked in
beside the run it came from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from temper import prose
from temper.comparison import compare
from temper.markup import Markup, element, join
from temper.wording import plural, span

if TYPE_CHECKING:
    from collections.abc import Sequence

    from temper.comparison import Comparison
    from temper.graders import Grade
    from temper.results import Manifest, Run, TrialFailure, TrialResult
    from temper.stats import Difference, Rate

# Characters of one text shown on the page; the rest stays in results.jsonl.
CLIP: Final = 4_000

_POLICY: Final = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"

_STYLE: Final = """
:root {
  color-scheme: light dark;
  --ink: #1f2328; --dim: #57606a; --line: #d0d7de; --paper: #ffffff; --wash: #f6f8fa;
  --better: #1a7f37; --worse: #b3261e; --track: #e6e9ed; --range: #8c959f;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ink: #e6edf3; --dim: #9198a1; --line: #3d444d; --paper: #0d1117; --wash: #161b22;
    --better: #57ab5a; --worse: #f47067; --track: #262c36; --range: #6e7681;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0 auto; max-width: 64rem; padding: 2rem 1rem 4rem;
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  color: var(--ink); background: var(--paper);
}
h1 { font-size: 1.6rem; margin: 0 0 0.25rem; }
h2 { font-size: 1.2rem; margin: 2.5rem 0 0.75rem; }
h3 { font-size: 1rem; margin: 1.25rem 0 0.5rem; }
p { margin: 0.25rem 0; }
a { color: inherit; text-underline-offset: 0.15em; }
.dim { color: var(--dim); }
.better { color: var(--better); }
.worse { color: var(--worse); }
.verdict {
  margin: 1.5rem 0; padding: 0.75rem 1rem; border: 2px solid; border-radius: 6px;
  font-weight: 600;
}
.verdict.ship { border-color: var(--better); }
.verdict.hold { border-color: var(--worse); }
.tally { font-size: 1.15rem; font-weight: 600; margin-top: 1.5rem; }
.table { overflow-x: auto; margin-top: 1.5rem; }
table { border-collapse: collapse; width: 100%; }
caption { text-align: left; color: var(--dim); padding-bottom: 0.5rem; }
th, td {
  text-align: left; vertical-align: top;
  padding: 0.4rem 0.75rem 0.4rem 0; border-bottom: 1px solid var(--line);
}
th { font-weight: 600; }
th[scope="row"], td.count, td.likely { white-space: nowrap; }
td.count { font-variant-numeric: tabular-nums; }
.bar {
  display: inline-block; position: relative; width: 8rem; height: 0.6rem;
  margin-right: 0.5rem; background: var(--track); border-radius: 3px; vertical-align: middle;
}
.bar span { position: absolute; }
.bar .range { top: 0; bottom: 0; background: var(--range); border-radius: 3px; }
.bar .point { top: -0.2rem; bottom: -0.2rem; width: 2px; background: var(--ink); }
.bar .zero { top: -0.2rem; bottom: -0.2rem; left: 50%; width: 1px; background: var(--dim); }
.bar.worse .range { background: var(--worse); }
.bar.better .range { background: var(--better); }
details { border-bottom: 1px solid var(--line); padding: 0.5rem 0; }
summary { cursor: pointer; font-weight: 600; }
.turn { margin: 0.5rem 0; }
.trial { margin: 0.75rem 0 1rem; padding-left: 0.75rem; border-left: 3px solid var(--line); }
ul.grades { margin: 0.25rem 0; padding-left: 1.25rem; }
pre {
  white-space: pre-wrap; overflow-wrap: anywhere; margin: 0.5rem 0;
  padding: 0.75rem; background: var(--wash); border-radius: 6px; font-size: 0.9rem;
}
footer { margin-top: 3rem; color: var(--dim); font-size: 0.9rem; }
@media (max-width: 40rem) {
  .bar { display: none; }
  th[scope="row"], td.likely { white-space: normal; overflow-wrap: anywhere; }
  th, td { padding-right: 0.5rem; }
}
"""


def build_scorecard(run: Run, baseline: Run | None = None) -> str:
    """The page for `run`, set against `baseline` when one is given.

    Raises:
        RunError: the two runs aren't of the same cases.
    """
    compared = compare(baseline, run) if baseline is not None else None
    manifest = run.manifest
    sections = [
        _header(manifest),
        _verdict(compared) if compared is not None else None,
        _summary(run, compared),
        _comparison_table(compared) if compared is not None else _run_table(run),
        _trials(run, baseline),
        _footer(manifest),
    ]
    title = f"{manifest.suite} · Temper scorecard"
    head = element(
        "head",
        element("meta", charset="utf-8"),
        element("meta", name="viewport", content="width=device-width, initial-scale=1"),
        element("meta", http_equiv="Content-Security-Policy", content=_POLICY),
        element("title", title),
        element("style", Markup(_STYLE)),
    )
    page = element("html", head, element("body", element("main", *sections)), lang="en")
    return f"<!doctype html>\n{page.html}\n"


def _header(manifest: Manifest) -> Markup:
    when = manifest.finished_at or manifest.started_at
    return element(
        "header",
        element("h1", manifest.suite),
        element("p", f"Run {manifest.run_id} · {prose.described(manifest)}", class_="dim"),
        element("p", f"{when:%m.%d.%Y %H:%M} UTC", class_="dim"),
    )


def _verdict(compared: Comparison) -> Markup:
    return element(
        "p", prose.verdict(compared), class_=f"verdict {'ship' if compared.ship else 'hold'}"
    )


def _summary(run: Run, compared: Comparison | None) -> Markup:
    lines: list[Markup | None] = [element("p", prose.tally(run), class_="tally")]
    lines.extend(element("p", said) for said in prose.left_out(run))
    if compared is not None and (overall := prose.overall(compared)) is not None:
        lines.append(element("p", overall))
    if run.rate.scored:
        lines.append(element("p", prose.noise(run.rate), class_="dim"))
    if (flaky := prose.flaky(run)) is not None:
        lines.append(element("p", flaky, class_="dim"))
    if (cost := prose.cost(run)) is not None:
        lines.append(element("p", cost, class_="dim"))
    return element("section", *lines, aria_label="Summary")


def _run_table(run: Run) -> Markup:
    failures = prose.failures_by_case(run.failures)
    rates = run.rates
    rows = [
        element(
            "tr",
            element("th", element("a", case_id, href=f"#case-{case_id}"), scope="row"),
            element("td", f"{rates[case_id].passed}/{rates[case_id].scored}", class_="count"),
            element("td", _likely(rates[case_id]), class_="likely"),
            element("td", prose.notes(rates[case_id], results, failures.get(case_id, []))),
        )
        for case_id, results in run.by_case().items()
    ]
    return _table(
        "Each case's pass rate, and the range its true rate is likely in (95%).",
        ("Case", "Passed", "Likely rate", "Notes"),
        rows,
    )


def _comparison_table(compared: Comparison) -> Markup:
    rows = [
        element(
            "tr",
            element(
                "th", element("a", change.case_id, href=f"#case-{change.case_id}"), scope="row"
            ),
            element("td", _count(change.difference.baseline), class_="count"),
            element("td", _count(change.difference.candidate), class_="count"),
            element("td", _change(change.difference), class_="likely"),
        )
        for change in compared.changes
    ]
    return _table(
        "Each case set against its twin in the baseline run, with how sure the change is (95%).",
        ("Case", "Baseline", "Candidate", "Change"),
        rows,
    )


def _table(caption: str, headers: Sequence[str], rows: Sequence[Markup]) -> Markup:
    heading = element("tr", *(element("th", header, scope="col") for header in headers))
    table = element(
        "table", element("caption", caption), element("thead", heading), element("tbody", *rows)
    )
    return element("div", table, class_="table")


def _count(rate: Rate) -> str:
    return f"{rate.passed}/{rate.scored}"


def _likely(rate: Rate) -> Markup:
    """The interval as words, with a bar beside it for the eye, which a screen reader skips."""
    if rate.value is None:
        return join("nothing scored")
    lower, upper = rate.interval
    bar = element(
        "span",
        element("span", class_="range", style=f"left:{lower:.1%};width:{upper - lower:.1%}"),
        element("span", class_="point", style=f"left:{rate.value:.1%}"),
        class_="bar",
        aria_hidden="true",
    )
    return join(bar, span(rate.interval))


def _change(difference: Difference) -> Markup:
    """The change as words, coloured by its direction, with its interval on a bar around zero."""
    direction = difference.direction
    words = element("span", prose.changed(difference), class_=direction)
    if difference.value is None:
        return words
    lower, upper = difference.interval
    bar = element(
        "span",
        element("span", class_="zero"),
        element(
            "span",
            class_="range",
            style=f"left:{(lower + 1) / 2:.1%};width:{(upper - lower) / 2:.1%}",
        ),
        element("span", class_="point", style=f"left:{(difference.value + 1) / 2:.1%}"),
        class_=f"bar {direction}" if direction else "bar",
        aria_hidden="true",
    )
    return join(bar, words)


def _trials(run: Run, baseline: Run | None) -> Markup:
    """Every case opened up: the question, then each trial's answer and grades."""
    candidates = run.by_case()
    before = baseline.by_case() if baseline is not None else {}
    failures = prose.failures_by_case(run.failures)
    rates = run.rates
    cases = []
    for case_id, results in candidates.items():
        rate = rates[case_id]
        asked = results[0].request.messages if results else ()
        parts: list[Markup | None] = [
            element("summary", f"{case_id} · {rate.passed}/{rate.scored} passed"),
            *(
                element(
                    "p", element("strong", f"{turn.role}: "), _clip(turn.content), class_="turn"
                )
                for turn in asked
            ),
        ]
        if baseline is not None:
            parts.append(element("h3", "Candidate"))
        parts.extend(_trial(result) for result in results)
        parts.extend(_failed(failure) for failure in failures.get(case_id, []))
        if baseline is not None:
            parts.append(element("h3", "Baseline"))
            parts.extend(_trial(result) for result in before.get(case_id, []))
        cases.append(element("details", *parts, id=f"case-{case_id}"))
    return element("section", element("h2", "Every trial"), *cases)


def _trial(result: TrialResult) -> Markup:
    status = "" if result.status == "complete" else f" · {result.status}, not scored"
    return element(
        "div",
        element("p", element("strong", f"Trial {result.trial}"), status, class_="dim"),
        element("pre", _clip(result.completion.text)),
        element("ul", *(_grade(grade) for grade in result.grades), class_="grades"),
        class_="trial",
    )


_VERDICT: Final = {
    True: ("passed", "better"),
    False: ("failed", "worse"),
    None: ("no verdict", None),
}


def _grade(grade: Grade) -> Markup:
    word, tone = _VERDICT[grade.passed]
    return element(
        "li", element("span", word, class_=tone), f" · {grade.check} · ", _clip(grade.reason)
    )


def _failed(failure: TrialFailure) -> Markup:
    heading = element("strong", f"Trial {failure.trial}")
    return element(
        "div",
        element("p", heading, f" · no answer, not scored · {failure.kind}", class_="dim"),
        element("p", f"{failure.reason} ({plural(failure.attempts, 'attempt')})"),
        class_="trial",
    )


def _clip(text: str) -> str:
    """The text, or as much as the page shows of it, saying how much more there is."""
    if len(text) <= CLIP:
        return text
    rest = len(text) - CLIP
    return f"{text[:CLIP]}… ({rest:,} more characters are in results.jsonl)"


def _footer(manifest: Manifest) -> Markup:
    return element(
        "footer",
        element(
            "p",
            "Pass rates are shown with 95% Wilson intervals, and changes with Newcombe's interval "
            "on the difference. A change is beyond noise when its interval leaves zero behind.",
        ),
        element(
            "p",
            f"Made by Temper {manifest.temper_version}. Costs are at list prices as of "
            f"{manifest.priced_on}.",
        ),
    )
