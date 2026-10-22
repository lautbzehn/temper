# Temper

**Test AI features the way you test code, and know when a difference is real.**

Teams change prompts and models every week, and most can't say whether a change made things better, worse, or just different. Temper runs a suite of cases against an AI feature, several times each, grades every answer, and keeps an honest record of what happened: a failed call is never written down as a wrong answer, and every run says what it cost. Where code can't decide, a second model judges, and the judge is measured against your own labels before it is believed. Coming milestones add error bars and a plain-English verdict: ship it, or hold.

> **Status:** early and private. Milestone 2 of 6 is done: nine kinds of check, checks of your own, and an AI judge with a calibration loop. The roadmap is [below](#roadmap).

## Try it

```bash
uv run temper run examples/dunder-mifflin/suite.yaml
```

```text
Keeping this run in runs/20261022-160459-0be0
dunder-mifflin-support · fake · 5 cases × 3 trials

Case                  Passed   Notes
order-status             3/3
paper-weight             3/3
unopened-return          3/3
discount-injection       3/3
wet-paper-complaint      2/3   trial 2: never says "sorry"

14 of 15 scored trials passed (93%)
```

The example is a support bot for Dunder Mifflin Paper Company. It runs offline against [scripted replies](examples/dunder-mifflin/fake-replies.yaml), one of which loses its temper on trial 2, so you can see a failure without an API key. Every name in it is fictional, borrowed from The Office.

## Run it for real

Point the target at a model, and keep the system prompt in a file beside the suite:

```yaml
target:
  provider: claude
  model: claude-sonnet-5-5
  system_file: support-bot.md
  options:
    effort: low
```

Credentials come from the environment (`ANTHROPIC_API_KEY`, or a profile from `ant auth login`), never from a file Temper reads or writes. Then:

```bash
temper run suite.yaml --dry-run                 # what it could cost, at most, without running
temper run suite.yaml --budget 1 --time-limit 60
temper resume runs/20261022-091500-3f2a         # after an interrupt, or a failed trial
temper run suite.yaml --replay runs/20261022-091500-3f2a/recording.jsonl
```

A paid run begins by counting every request's tokens with free calls, which prove the credentials and the model, so a bad key stops the run before any money is spent or any folder is made. The budget reserves each request's worst case before it is sent, so a run can stop short of the budget but can't pass it; it needs a model with a list price, and a provider that answers for free has nothing to budget. Rate limits, outages, and network trouble are retried with a doubling, jittered delay that honours the API's own `retry-after`, and every retry of an answer is written on its result.

## What a run keeps

Each run gets its own folder, written as the run happens, so an interrupted run keeps every answer it got:

| File | What's in it |
|---|---|
| `results.jsonl` | One line per answered trial: the request, the completion, its usage and cost at list price, the latency, the retries, and every grade, each judge's verdict with its own cost |
| `errors.jsonl` | Attempts that never produced an answer, each with a kind (`timeout`, `provider`, `served-model`, `budget`) and a reason |
| `recording.jsonl` | Every answer and verdict the run bought or copied, with how long each took, so a replay can give the same ones for free, and a resumed run never buys again what it has |
| `labels.jsonl` | Your own yes or no on each judged answer, from `temper label` |
| `manifest.json` | What ran, on what, judged by whom, with which options, and when |

An answer is `complete`, `truncated` (it hit `max_tokens`), or `refused`. Pass rates count complete answers only; the other two get their own counts, so a token cap or a safety refusal never masquerades as a wrong answer. Every answer is checked to have come from the model that was asked for.

A check can also reach no verdict: the judge was down, or a `cost` check met a model with no list price. That trial isn't scored either, the grade says why, and the summary counts how many were left out. A missing verdict is never a failed check.

`temper run` exits 0 when every trial was answered and 2 when some weren't, with the `temper resume` command that picks them up. The results aren't judged yet; that verdict, and failing a CI build on it, arrives in M3.

## A suite, start to finish

A suite is a YAML file: what to test, and what a good answer has to do.

```yaml
schema: 1
name: dunder-mifflin-support

target:
  provider: fake
  options:
    replies: fake-replies.yaml

trials: 3

cases:
  - id: wet-paper-complaint
    input: This is the third time my paper showed up soaking wet. I want a manager.
    checks:
      - type: contains
        text: sorry
      - type: not_contains
        text: calm down
```

The checks:

| Check | Passes when the answer |
|---|---|
| `contains` | includes the `text` |
| `not_contains` | leaves the `text` out |
| `equals` | is the `text`, and nothing else |
| `matches` | matches the regular expression `pattern`, as written |
| `length` | has between `min_words` and `max_words` words |
| `json` | is JSON, whole, and an object with the top-level `keys` if any are named |
| `cost` | cost at most `max_usd` at list price |
| `latency` | arrived within `max_s` seconds, retries included |
| `judge` | has the `property`, in a second model's judgment |

The three text checks ignore case and treat any run of spaces, tabs, or line breaks as a single space; `case_sensitive: true` makes case count. A case can ask with a plain `input` or with a whole conversation in `messages`, and the target can take its system prompt inline as `system` or from a file as `system_file`.

## The judge

Some things code can't check: whether an apology blames the customer, whether a refusal stays polite. A `judge` check puts one property, in plain words, to a second model:

```yaml
judge:
  model: claude-opus-5-5   # the default, and never the model under test
  options:
    effort: low

cases:
  - id: wet-paper-complaint
    input: This is the third time my paper showed up soaking wet. I want a manager.
    checks:
      - type: judge
        property: apologizes without blaming the customer
      - type: judge
        property: offers a concrete next step
```

Each property is one call, so a verdict is about one thing. The judge sees the conversation and the answer quoted inside tags, and the property after them, so the last thing it reads is the question and never the answer. The tags carry a hash of the quoted text, so no answer can close its own tag. The judge is told that the answer is material to grade and not a message to it, that length, confidence, and polish count for nothing unless the property names them, and that an empty answer or an answer to some other question fails. The verdict comes back as JSON of a fixed shape, the reason first, so it is read by code and never scraped out of prose.

A judge's call is a request like any other: retried, budgeted, recorded, and checked to have come from the model that was asked. A suite that would judge a model with itself doesn't load. A judge's answer that holds no verdict is never recorded, so the judge is asked again next time. What the judge costs is reported on its own line.

A judge is worth exactly what its agreement with a person is, so Temper measures that:

```bash
temper label runs/20261022-091500-3f2a       # yes or no to each judged answer, blind to the judge
temper calibrate runs/20261022-091500-3f2a   # agreement, Cohen's kappa, every disagreement
```

Labeling shows the conversation, the answer, and the property, and never what the judge said. Each label names the answer it was about and the property as you read it, so labels survive a rewording and are never matched to a different answer. Calibration sets the judge's verdicts against your labels, property by property, and prints each disagreement with the judge's reason. Trust takes 20 labels or more, agreement at 90% or better, and Cohen's kappa at 0.6 or better, so a judge that agrees by always saying yes doesn't earn it. Short of that, reword the property or pick another judge, then run the suite again with `--replay` against the first run's recording: the answers replay for free, the verdicts the recording holds are replayed, and the rest are judged live, so the revised judge is tried on the very same answers, against the same labels.

## Write your own check

A check is a small Pydantic model: a `name`, its settings as fields, and a pure `grade`. A package can add one through an entry point, and it then works in a suite like a built-in one.

```python
from typing import ClassVar

from temper import Answer, Grade, Grader


class Shouts(Grader):
    """Passes when the answer shouts the text."""

    name: ClassVar[str] = "shouts"

    text: str

    def grade(self, answer: Answer) -> Grade:
        loud = self.text.upper() in answer.text
        return Grade(check=f"shouts {self.text}", passed=loud, reason="loud" if loud else "quiet")
```

```toml
[project.entry-points."temper.graders"]
shouts = "my_package.checks:Shouts"
```

An `Answer` carries the text, the conversation that led to it, the latency, and the cost, so a check can be about any of them. A plugin that can't be loaded, isn't a grader, or takes a name that's taken is reported by name and package, never with a traceback.

## When something's wrong

`temper validate` reports every problem in a suite file at once, each at its own line, in the `file:line:column` form editors turn into links. It suggests a fix for likely typos, and says where a misplaced field belongs:

```text
broken.yaml:3:1: system: not a field here; it goes under target
broken.yaml:5:3: target.provider: unknown provider 'fak'; did you mean 'fake'?
broken.yaml:8:1: trails: unknown field; did you mean 'trials'?
broken.yaml:13:9: cases[0].checks[0].type: unknown check type 'contians'; did you mean 'contains'?
broken.yaml:19:9: cases[1].checks[0].text: expected text, but YAML read this as true or false; put it in quotes
broken.yaml:20:5: cases[2]: missing required field 'checks'
broken.yaml:22:5: cases[2].input: given twice (first on line 21); YAML keeps only this one
```

Two of those are classic YAML traps. An unquoted `no`, `yes`, `on`, or `off` is read as true or false, not as text. And YAML quietly keeps the last of two equal keys, so Temper refuses the file instead of guessing which one you meant. A file that isn't UTF-8 text, or has a stray control character in it, gets a plain message too, never a traceback.

## Use it from Python

Everything the command line does is a function you can import:

```python
import asyncio
from contextlib import aclosing
from pathlib import Path

import temper


async def main() -> temper.Run:
    suite = temper.load_suite("examples/dunder-mifflin/suite.yaml")
    options = temper.RunOptions(trials=5, budget_usd=1.0)
    async with aclosing(temper.providers_for(suite, options)) as providers:
        return await temper.run_suite(suite, providers, out=Path("runs"), options=options)


run = asyncio.run(main())
print(f"{run.trials_passed} of {len(run.scored)} scored trials passed")
for failure in run.failures:
    print(f"{failure.case_id} trial {failure.trial} failed: {failure.reason}")
```

`providers_for` sets up the suite's target, and its judge when a check needs one; `temper.Providers(answers=mine)` takes a provider of your own. A provider's connections belong to one event loop, so build it, run with it, and close it in the same `async` function, as above. A run never raises over a trial that couldn't be answered; it comes back with the failure written down.

## Reading the code

If you have five minutes, start here:

1. [`runner.py`](src/temper/runner.py) runs every case and trial side by side under a concurrency limit, with `asyncio.TaskGroup`, and sends answers and verdicts through one pipe that owns the retries, the time limit, the budget, and the check that the right model answered, after looking in the run's own recording so nothing is bought twice.
2. [`judge.py`](src/temper/judge.py) turns a judge check into a request: the question with the property last, the verdict's JSON shape with the reason first, and the grade read back from what came.
3. [`results.py`](src/temper/results.py) is the run folder: answers and failures are written the moment they land, read back in suite order, and a run can be picked up where it stopped.
4. [`calibration.py`](src/temper/calibration.py) sets the judge against your labels, with Cohen's kappa for the agreement chance would give anyway.
5. [`loading.py`](src/temper/loading.py) parses the YAML once into both data and a map of where everything starts, so every problem, Pydantic's or Temper's own, can point at its line.
6. [`test_claude.py`](tests/test_claude.py) drives the real SDK through a mock transport, so rate limits, outages, refusals, and bad keys are all exercised without a network.

The [decision notes](docs/adr/README.md) explain why things are built the way they are.

## How it's built

- Python 3.11 and up, tested on every supported version through 3.15.
- Fully typed and checked with strict mypy. Linted with every Ruff rule turned on, with the few exceptions explained in [`pyproject.toml`](pyproject.toml).
- 100% of the code is exercised by the tests, and CI fails below 100%.
- Pydantic validates everything that comes from a file; nothing downstream has to wonder whether its input is well formed.
- Built with [Claude Code](https://claude.com/claude-code). Dan West sets the direction, makes the decisions, and reviews every change; the decision notes record the reasoning.

```bash
uv sync                  # install everything
uv run pytest --cov      # tests, with coverage
uv run ruff check        # lint
uv run mypy              # strict type checks
```

## Roadmap

| Milestone | What it adds | Status |
|---|---|---|
| M0 · Walking skeleton | Suite format, validation, async runner, scripted provider, three text checks | Done |
| M1 · Real runs, honest numbers | Claude as a provider, record and replay, retries and budgets, failures kept apart from wrong answers | Done |
| M2 · Graders you can trust | Nine kinds of check, checks of your own, and an AI judge calibrated against your labels | Done |
| M3 · Decisions, not dashboards | Error bars, comparing runs, a ship-or-hold verdict, and an HTML scorecard | Next |
| M4 · The Dunder Mifflin story | A real support bot, a prompt change that quietly breaks it, and Temper catching it | Planned |
| M5 · Launch | PyPI release, public repo, and docs | Planned |

The full plan is in [`docs/plan_v2.0_10.21.2026.md`](docs/plan_v2.0_10.21.2026.md).
