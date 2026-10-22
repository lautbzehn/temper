# Changelog

All notable changes to Temper. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.2.0] · 10.22.2026

Real runs, honest numbers: Claude answers the cases, and every attempt is written down for what it was.

### Added

- The `claude` provider, on the Anthropic SDK with its own retries off. A target names the model; `options` can set `effort` and `timeout_s`.
- The `replay` provider and `temper run --replay`, which answer from a `recording.jsonl` that every paid run writes, and refuse a trial whose prompt has changed since.
- Retries of transient trouble with doubling, jittered backoff that honours `retry-after`, written on each result; `--attempts` sets the limit.
- `--time-limit` per trial, retries included, and `--budget`, which reserves each request's worst case so a run can't overspend. A budget is refused up front on a model with no list price, and means nothing to a provider that answers for free.
- `--dry-run`, which counts each case's tokens and prices the worst case without running.
- `temper resume`, which picks up a kept run and answers only the trials that still have no answer. `temper run` exits 2 while any trial is unanswered.
- `errors.jsonl` for attempts that never produced an answer, with a kind and a reason, kept apart from `results.jsonl`.
- Answer statuses: `complete`, `truncated`, and `refused`. Pass rates count complete answers only; the others get their own counts.
- A check that the model that answered is the one asked for.
- Cost at list price from the API's own token counts, failures included, and a free preflight before any paid run, done before the run's folder exists so a run that can't start leaves nothing behind.

### Changed

- `results.jsonl` lines now hold the whole transcript: the request, the completion with its usage, the cost, the attempts, and the grades. Runs kept by 0.1.0 can't be read back.
- `run_suite` keeps every run on disk and takes `out=`; `Run.trials_passed` counts complete answers only.
- A loaded suite knows its file as `suite.path`, and option suggestions come from the named provider alone.

## [0.1.0] · 10.22.2026

The walking skeleton: a suite goes in, graded results come out.

### Added

- The suite format, schema version 1: a target, trials, and cases with checks, in YAML.
- `temper validate`, which reports every problem in a suite at once, each at its line and column, in plain words: suggestions for likely typos, where a misplaced field belongs, keys given twice, and YAML's true-or-false and number traps. Files that aren't UTF-8 or aren't valid YAML get a message, never a traceback.
- `temper run`, which asks every case several times side by side, grades each answer, prints a summary, and keeps the run as `manifest.json` plus `results.jsonl`.
- Three checks: `contains`, `not_contains`, and `equals`, each ignoring case and collapsing runs of whitespace by default.
- The fake provider, which answers from scripted replies so suites run offline.
- A Dunder Mifflin starter suite in `examples/`.
- A Python API: `load_suite`, `build_provider`, `run_suite`, and `write_run`.
