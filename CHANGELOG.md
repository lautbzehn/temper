# Changelog

All notable changes to Temper. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] · Unreleased

The walking skeleton: a suite goes in, graded results come out.

### Added

- The suite format, schema version 1: a target, trials, and cases with checks, in YAML.
- `temper validate`, which reports every problem in a suite at once, each at its line and column, in plain words: suggestions for likely typos, where a misplaced field belongs, keys given twice, and YAML's true-or-false and number traps. Files that aren't UTF-8 or aren't valid YAML get a message, never a traceback.
- `temper run`, which asks every case several times side by side, grades each answer, prints a summary, and keeps the run as `manifest.json` plus `results.jsonl`.
- Three checks: `contains`, `not_contains`, and `equals`, each ignoring case and collapsing runs of whitespace by default.
- The fake provider, which answers from scripted replies so suites run offline.
- A Dunder Mifflin starter suite in `examples/`.
- A Python API: `load_suite`, `build_provider`, `run_suite`, and `write_run`.
