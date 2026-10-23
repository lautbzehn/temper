# Temper

## The goal comes first

Temper exists to show that Dan West writes excellent Python. The code is the product: elegant, neat, worth sharing, and impressive to anyone who reviews it. When a feature and the quality bar disagree, cut the feature.

Owner: Dan West. Repo: `lautbzehn/temper`, private until Dan makes it public at the v1.0 launch. Roadmap: [docs/plan_v2.0_10.21.2026.md](docs/plan_v2.0_10.21.2026.md).

## The quality bar, on every change

- Small modules with one job each, short functions, and names that say what things do.
- Modern, idiomatic Python 3.11+. Fully typed. No `Any` in a public signature without a reason, and no `type: ignore` or `noqa` without a code and a reason.
- `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, and `uv run pytest --cov` all pass, with coverage at 100%.
- Docstrings say why, not what. Comments are rare and earn their place.
- No dead code, no TODOs, no clever tricks.
- Errors are written for people: what is wrong, where, and what to do about it.
- Before each milestone's hard stop: an editor's pass to simplify, then a fresh-eyes review that asks whether a senior Python engineer would be impressed.

## Eval honesty

- Plumbing failures (timeouts, rate limits, crashes) are kept apart from wrong answers and never scored as the model's fault.
- Cut-off answers and refusals get labels of their own.
- Every call checks that the model that answered is the one that was asked.
- Cost comes from the API's own token counts. Every trial keeps its full transcript.
- The judge is never the model under test, and its agreement with human labels is measured and reported.

## What Dan's commands mean

- **"Change ..."**: branch from the latest `main`, make the change, run the checks, push, and open a pull request. Don't merge yet. Reply with what changed in plain words.
- **"Ship"**: merge the open pull request with a merge commit. If it finishes a milestone, tag the release (`vX.Y.Z`) and publish it on GitHub: as a pre-release before v1.0, and as a full release from v1.0 on, because PyPI and the demo site publish only on a full release. A release that publishes to PyPI waits for Dan's go, since PyPI can't take a version back.
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
uv run temper run examples/dunder-mifflin/suite.yaml --dry-run
uv run temper demo
uv run pytest --cov
uv run ruff check && uv run ruff format --check
uv run mypy
```

## Layout

| Path | What lives there |
|---|---|
| `src/temper/suite.py` | The suite format, schema version 1 (frozen against breaking changes) |
| `src/temper/loading.py` | YAML to a validated suite, with every problem at its line |
| `src/temper/graders.py` | Checks: validated models with a pure `grade`, and the `judge` check's settings |
| `src/temper/checks.py` | Finding a check by name: the built-ins, the judge, and any a plugin adds |
| `src/temper/judge.py` | The judge: its prompt with sealed tags, the verdict's JSON shape, and the grade read back from a completion |
| `src/temper/plugins.py` | Checks other packages add, found through the `temper.graders` entry point group |
| `src/temper/providers/` | Where answers come from: the `Provider` protocol (`base.py`), and the `claude`, `fake`, and `replay` providers |
| `src/temper/pricing.py` | List prices, and what a `Usage` costs |
| `src/temper/planning.py` | Before a run: who answers, counting every request, the worst case a budget holds |
| `src/temper/runner.py` | Async runs: answers and verdicts through one pipe with retries, time limits, budget, served-model check, recordings first, resume |
| `src/temper/results.py` | The run folder: `results.jsonl`, `errors.jsonl`, `recording.jsonl`, and `manifest.json` |
| `src/temper/labels.py`, `labeling.py` | A person's labels on judged answers, and the blind session that collects them |
| `src/temper/calibration.py` | The judge against the labels: agreement, Cohen's kappa, and every disagreement |
| `src/temper/stats.py` | Wilson intervals, Newcombe's interval on a change, the noise floor, trials to tell a change |
| `src/temper/comparison.py` | Two runs of the same cases side by side, and the ship-or-hold call |
| `src/temper/doctor.py` | The check-up: Python, credentials by source, models, the runs folder, an offline run |
| `src/temper/prose.py` | The sentences both reports say about a run or a comparison, so they never disagree |
| `src/temper/summary.py` | The terminal summary, the dry-run estimate, the calibration report, the comparison, the check-up |
| `src/temper/markup.py` | Building HTML so text can never become markup: everything escaped on the way in |
| `src/temper/scorecard.py` | The single-file HTML scorecard: loads nothing, runs nothing, same run same page |
| `src/temper/demo/` | The Dunder Mifflin story: the 40-case suite, both prompts, their recordings, and the replay behind `temper demo` |
| `src/temper/cli.py` | The `temper` command, a thin layer over the library |
| `src/temper/errors.py` | Every error a person might see |
| `src/temper/files.py`, `jsonl.py`, `wording.py` | Reading files as UTF-8, records one per line, and the plurals and dollars people read |
| `docs/adr/` | Decision notes: the context, the decision, and what it costs |
| `docs/quickstart_*`, `docs/architecture_*` | Five steps to a first call, and how the pieces fit |
| `.github/workflows/` | CI on every change; on a published release, PyPI through trusted publishing and the demo site on Pages |
