# Temper

**Test AI features the way you test code, and know when a difference is real.**

Teams change prompts and models every week, and most can't say whether a change made things better, worse, or just different. Temper runs a suite of cases against an AI feature, several times each, grades every answer, and keeps a clean record of what happened. Coming milestones add real models, a calibrated AI judge, error bars, and a plain-English verdict: ship it, or hold.

> **Status:** early and private. Milestone 0 of 6, the walking skeleton, is done: suites load and validate, run end to end against a scripted provider, and get graded. The roadmap is [below](#roadmap).

## Try it

```bash
uv run temper run examples/dunder-mifflin/suite.yaml
```

```text
dunder-mifflin-support · fake · 5 cases × 3 trials

Case                  Passed   First failure
order-status             3/3
paper-weight             3/3
unopened-return          3/3
discount-injection       3/3
wet-paper-complaint      2/3   trial 2: never says "sorry"

14 of 15 trials passed (93%) · kept in runs/20261022-023403-cca1
```

The example is a support bot for Dunder Mifflin Paper Company. It runs offline against [scripted replies](examples/dunder-mifflin/fake-replies.yaml), one of which loses its temper on trial 2, so you can see a failure without an API key. Every name in it is fictional, borrowed from The Office.

Each run is kept in its own folder: a `manifest.json` saying what ran, on what, and when, plus `results.jsonl` with one line per trial, every answer, and every grade.

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

Checks available today:

| Check | Passes when the answer |
|---|---|
| `contains` | includes the text |
| `not_contains` | leaves the text out |
| `equals` | is the text, and nothing else |

Each one ignores case and spacing, unless the check sets `case_sensitive: true`. A case can ask with a plain `input` or with a whole conversation in `messages`, and the target can take its system prompt inline as `system` or from a file as `system_file`.

## When something's wrong

`temper validate` reports every problem in a suite file at once, each at its own line, in the `file:line:column` form editors turn into links, and suggests a fix for likely typos:

```text
broken.yaml:4:3: target.provider: unknown provider 'fak'; did you mean 'fake'?
broken.yaml:7:1: trails: unknown field; did you mean 'trials'?
broken.yaml:12:9: cases[0].checks[0].type: unknown check type 'contians'; did you mean 'contains'?
broken.yaml:14:5: cases[1]: give exactly one of `input` or `messages`
broken.yaml:21:9: cases[1].checks[0].text: expected text, but YAML read this as true or false; put it in quotes
broken.yaml:22:5: cases[2]: missing required field 'checks'
```

That fifth line catches a classic YAML trap: an unquoted `no`, `yes`, `on`, or `off` is read as true or false, not as text.

## Use it from Python

Everything the command line does is a function you can import:

```python
import asyncio
from pathlib import Path

import temper

suite = temper.load_suite("examples/dunder-mifflin/suite.yaml")
provider = temper.build_provider(suite.target, Path("examples/dunder-mifflin"))
run = asyncio.run(temper.run_suite(suite, provider, trials=5))

print(f"{run.passed} of {len(run.results)} trials passed")
```

## Reading the code

If you have five minutes, start here:

1. [`loading.py`](src/temper/loading.py) parses the YAML once into both data and a map of where everything starts, so every problem, Pydantic's or Temper's own, can point at its line.
2. [`runner.py`](src/temper/runner.py) runs every case and trial side by side under a concurrency limit, with `asyncio.TaskGroup`, and hands results back in suite order whatever order they finish in.
3. [`graders.py`](src/temper/graders.py) makes each grader a small validated model whose `grade` method is a pure function of the answer.
4. [`test_graders.py`](tests/test_graders.py) checks those graders against thousands of generated inputs with Hypothesis, not just a handful of examples.

The [decision notes](docs/adr/README.md) explain why things are built the way they are.

## How it's built

- Python 3.11 and up, tested on every supported version through 3.15.
- Fully typed and checked with strict mypy. Linted with every Ruff rule turned on, with the few exceptions explained in [`pyproject.toml`](pyproject.toml).
- 100% of the code is exercised by the tests, and CI requires at least 90%.
- Pydantic validates everything that comes from a file; nothing downstream has to wonder whether its input is well formed.
- Built with [Claude Code](https://claude.com/claude-code). Dan West sets the direction, makes the decisions, and reviews every change; the decision notes record the reasoning.

```bash
uv sync                  # install everything
uv run pytest            # tests, with coverage
uv run ruff check        # lint
uv run mypy              # strict type checks
```

## Roadmap

| Milestone | What it adds | Status |
|---|---|---|
| M0 · Walking skeleton | Suite format, validation, async runner, scripted provider, three text checks | Done |
| M1 · Real runs, honest numbers | Claude as a provider, record and replay, retries and budgets, failures kept apart from wrong answers | Next |
| M2 · Graders you can trust | A plugin system for checks, and an AI judge calibrated against human labels | Planned |
| M3 · Decisions, not dashboards | Error bars, comparing runs, a ship-or-hold verdict, and an HTML scorecard | Planned |
| M4 · The Dunder Mifflin story | A real support bot, a prompt change that quietly breaks it, and Temper catching it | Planned |
| M5 · Launch | PyPI release, public repo, and docs | Planned |

The full plan is in [`docs/plan_v2.0_10.21.2026.md`](docs/plan_v2.0_10.21.2026.md).
