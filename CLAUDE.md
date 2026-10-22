# Temper

## The goal comes first

Temper exists to show that Dan West writes excellent Python. The code is the product: elegant, neat, worth sharing, and impressive to anyone who reviews it. When a feature and the quality bar disagree, cut the feature.

Owner: Dan West. Repo: `lautbzehn/temper`, private until v1.0. Roadmap: [docs/plan_v2.0_10.21.2026.md](docs/plan_v2.0_10.21.2026.md).

## The quality bar, on every change

- Small modules with one job each, short functions, and names that say what things do.
- Modern, idiomatic Python 3.11+. Fully typed. No `Any` in a public signature without a reason, and no `type: ignore` or `noqa` without a code and a reason.
- `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, and `uv run pytest --cov` all pass, with coverage at 100%.
- Docstrings say why, not what. Comments are rare and earn their place.
- No dead code, no TODOs, no clever tricks.
- Errors are written for people: what is wrong, where, and what to do about it.
- Before each milestone's hard stop: an editor's pass to simplify, then a fresh-eyes review that asks whether a senior Python engineer would be impressed.

## Eval honesty, from M1 on

- Plumbing failures (timeouts, rate limits, crashes) are kept apart from wrong answers and never scored as the model's fault.
- Cut-off answers and refusals get labels of their own.
- Every call checks that the model that answered is the one that was asked.
- Cost comes from the API's own token counts. Every trial keeps its full transcript.
- The judge is never the model under test, and its agreement with human labels is measured and reported.

## What Dan's commands mean

- **"Change ..."**: branch from the latest `main`, make the change, run the checks, push, and open a pull request. Don't merge yet. Reply with what changed in plain words.
- **"Ship"**: merge the open pull request with a merge commit. If it finishes a milestone, tag the release (`vX.Y.Z`) and publish it as a GitHub pre-release.
- **"Change and ship"**: both, merging only once CI passes.

## Rules

- Never push straight to `main`. Pull requests are how CI guards the code.
- Never put secrets in the repo or in chat. API keys come from the environment or `ant auth login`.
- A Claude Code hook (`.claude/hooks/check-python.sh`) formats, lints, and type-checks every Python file Claude edits, and hands problems straight back.
- Copy is plain, warm, and human, like explaining it over coffee. No em dashes.
- Documents carry a version and date (`vX.X` and `mm.dd.yyyy`) in the file name and on the document.
- Demo data is fictional: Dunder Mifflin, with The Office cast.
- Keep `.claude/tracker.json` current at every step. Dan's tracker panel reads it, and its Mark done buttons write back to it, so read it fresh before editing.
- Hard stop at the end of each milestone: walk Dan through it and wait for his go.

## Commands

```bash
uv sync
uv run temper validate examples/dunder-mifflin/suite.yaml
uv run temper run examples/dunder-mifflin/suite.yaml
uv run pytest --cov
uv run ruff check && uv run ruff format --check
uv run mypy
```

## Layout

| Path | What lives there |
|---|---|
| `src/temper/suite.py` | The suite format, schema version 1 (frozen against breaking changes) |
| `src/temper/loading.py` | YAML to a validated suite, with every problem at its line |
| `src/temper/graders.py` | Checks: validated models with a pure `grade` method |
| `src/temper/providers.py` | Where answers come from: the `Provider` protocol and the fake provider |
| `src/temper/runner.py` | Async runs under a concurrency limit, results in suite order |
| `src/temper/results.py` | Run records, and how they are written to disk |
| `src/temper/summary.py` | The terminal summary |
| `src/temper/cli.py` | The `temper` command, a thin layer over the library |
| `src/temper/errors.py` | Every error a person might see |
| `src/temper/files.py` | Reading files as UTF-8, with one kind of error for every way that fails |
| `docs/adr/` | Decision notes: the context, the decision, and what it costs |
