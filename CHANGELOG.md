# Changelog

All notable changes to Temper. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [1.0.0] · 10.23.2026

The launch. The suite format is version 1, frozen against breaking changes, and the library and command line follow semantic versioning from here.

### Added

- Releases publish to PyPI as `temper-evals` through trusted publishing: a published GitHub release builds the package, checks the tag is the version, proves the built wheel replays the demo with no key, and publishes. No token is stored anywhere.
- The story's scorecard is built by `temper demo` and served by GitHub Pages on each release.
- A [quickstart](docs/quickstart_v1.0_10.23.2026.md), from nothing to a ship-or-hold call in five steps, and an [architecture](docs/architecture_v1.0_10.23.2026.md) page with a diagram.
- An Apache-2.0 license, and the package metadata PyPI shows: the license, the project's links, and a Beta status.

### Changed

- The README's links are absolute, so they work on PyPI too, and it publishes the judge's measured agreement with a person's labels.

## [0.5.0] · 10.23.2026

The Dunder Mifflin story: a real recorded run of a prompt change that quietly breaks a support bot, and Temper catching it.

### Added

- `temper demo`: the story replayed from its recording, for free, offline, with no key. All 400 trials go through the harness again and every answer is graded again in code. The recording is the only provider the replay is given, for answers and verdicts alike, so nothing in it can reach the API. It prints the comparison and writes the story's scorecard.
- The story itself, shipped inside the package: a 40-case support suite with 58 checks (35 of them judged), the careful prompt, Dwight's tidy-up, and one live run of each, five trials per case, with the API's request ids left out of the shipped copies. The careful prompt passed all 200 trials; the tidy-up broke nine cases beyond noise and is held.
- `temper run --system FILE` answers the same cases with another system prompt, to compare two prompts. The scorecard names both runs and their prompts, and a dry run names the prompt it priced.

### Changed

- Planning swaps in a run's system prompt, and `start_run` takes the plan rather than a suite, so no path can answer one prompt while the manifest names another. A run's `replay` and `system` files are held as absolute paths, so a run resumes from any folder.

## [0.4.0] · 10.23.2026

Decisions, not dashboards: every number comes with how sure it is, and two runs end in a call.

### Added

- Every pass rate has its 95% interval, a Wilson score interval, shown per case and for the run. A run states its noise floor, the biggest difference two runs of the same thing could show by chance at its size, and names its flaky cases, the ones whose trials disagreed.
- `temper compare BASELINE CANDIDATE`: each case set against its twin with Newcombe's interval on the change, widened across the cases so one false alarm among them stays as unlikely as one alone; the overall change against the noise; and a verdict. Hold when anything got worse beyond noise, overall or on a single case; no call when a case has nothing scored in either run; ship otherwise, with the trials per case that would settle an undecided change. The report says when the two runs were judged by different models. `--fail-on-regression` exits 3 whenever the candidate can't ship, for CI.
- `temper doctor [SUITE]`: Python, credentials (by source, never shown), each model the suite needs, whether runs could be kept where they go, and an offline run, without spending anything or making a folder.
- A run's manifest carries a fingerprint of its cases alone, tags left out, so runs of one suite with different targets can be compared.
- `compare`, `Comparison`, `Rate`, `Difference`, and `build_scorecard` are importable from `temper`.
- `temper scorecard RUN [--baseline RUN] [--out FILE]`: one HTML file with the call, the tally, the noise floor, every case's likely range as a bar, and every trial's full answer and grades. Every text is escaped by a small builder, so a model's output can never become markup; the page loads nothing and runs nothing, under a content policy that forbids it; long answers are clipped; the same run makes the same page byte for byte. Light by default, dark when the reader prefers it, WCAG AA contrast in both.

### Changed

- The statistics live in `temper.stats` and the comparison in `temper.comparison`, both closed form and standard library only. The sentences the terminal and the scorecard share live in `temper.prose`.

## [0.3.1] · 10.22.2026

The first real labeling session found that `temper label` cropped the answers it asked about.

### Fixed

- `temper label` shows every answer in full. The command's console leaves long lines for the terminal to wrap, which is right for paths you might copy, but inside the answer's box Rich crops them instead, so each paragraph was cut at the box's edge. The labeling screen now wraps its text itself. The labeling tests now use a console set up the way the command's is, and a long answer must show whole.

### Docs

- The README names a YAML trap Temper can't catch: a space followed by `#` starts a comment, so an unquoted question with an order number in it loses everything from the `#` on. The judge pilot's own suite had it.

## [0.3.0] · 10.22.2026

Graders you can trust: more checks, checks of your own, and a judge that is measured before it is believed.

### Added

- Five checks: `matches` (a regular expression), `length` (word count bounds), `json` (the whole answer is JSON, with named keys), `cost` (at most so many dollars at list price), and `latency` (answered within so many seconds).
- The `judge` check: one property in plain words, decided by a second model. The judge sees the conversation and the answer quoted inside tags with the property after them, is told what not to reward, and answers in JSON of a fixed shape with the reason first. Each call goes through the runner like an answer: retried, budgeted, recorded, and checked for the model that answered. A suite's `judge` block picks the model and its options; a suite that would judge a model with itself doesn't load.
- `temper label`, which asks for a yes or no on each judged answer, blind to the judge, and `temper calibrate`, which reports agreement, Cohen's kappa, and every disagreement, with a 90% bar for trusting the judge.
- Checks from other packages, through the `temper.graders` entry point group. A plugin that can't be used is reported by name and package.
- A grade can reach no verdict: the judge was down, or a `cost` check met a model with no list price. The trial isn't scored, the grade says why, and the summary counts it apart.
- `--replay` replays verdicts too, and asks the judge live only for the ones the recording lacks, so a revised judge can be tried on the same answers.
- A replayed answer keeps its recorded latency, so a `latency` check means the same thing live and replayed.
- A resumed run answers from its own recording first, so an interrupt while judging never costs the answer again.
- The judge's tags carry a hash of the quoted text, so no answer can close its own tag. A judge's answer that holds no verdict is never recorded, so the judge is asked again on a replay.
- A label names the answer it was about and the property as it was worded, so calibration survives a rewording or a reorder and never scores a label against a different answer. Trust takes 20 labels, 90% agreement, and Cohen's kappa at 0.6.

### Changed

- The runner takes `Providers` (answers, judge, recording) where it took one provider, and `providers_for` builds them from a suite; planning a run (`plan_run`, `estimate_suite`, `Plan`) lives in `temper.planning`, and finding a check by name in `temper.checks`. Graders grade an `Answer`, which carries the text, the conversation, the latency, and the cost, rather than a bare string.
- A paid run counts every request's tokens before it starts, not just one, so a request cut off by the time limit is counted at its real worst case whether or not a budget was set.
- `--time-limit` and `--attempts` apply per request, an answer or a verdict each.

## [0.2.1] · 10.22.2026

The first live run found a bug the tests couldn't see. The command ran its free preflight in one event loop and the trials in another, with one API client between them, whose pooled connections belonged to the first loop. Every trial's first attempt failed with a connection error, and the retry hid it.

### Fixed

- `temper run` and `temper resume` plan, run, and close the provider in one event loop, so a connection the preflight opened is still good when the trials need it.
- Providers have an `aclose`, and the command closes the one it opened, so no connection is left open at exit.
- The package reports its version again: v0.2.0 still said `0.1.0`.

### Added

- A regression test that stands up a local HTTP server speaking the API's shape, so real connections are exercised without the network.

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
