# Temper roadmap

**v2.0 · 10.21.2026** · Owner: Dan West

## Why Temper exists

Temper's first job is to show excellent Python: code that is elegant, neat, and worth sharing. Its second job is a real one. Teams change prompts and models every week, and most can't tell whether a change made things better, worse, or just different. A pass rate without error bars leads to confident, wrong decisions.

- **Users:** the AI product manager deciding whether a change ships, and the engineer who wants that decision enforced in CI.
- **North star:** no prompt or model change ships with a regression nobody saw.
- **Positioning:** tools like promptfoo, Inspect, and DeepEval are capable, and Temper doesn't try to out-feature them. Its edge is honesty. It tells you whether a difference is real, keeps plumbing failures out of the score, proves its own judge against human labels, and ends in a ship-or-hold verdict a product manager can defend.

## Launch scorecard

| Measure | Target |
|---|---|
| Time to a first result on a fresh machine, with no API key | Under 2 minutes |
| Judge agreement with human labels | 90% or better, published |
| Planted regressions caught | 2 of 2, clearly beyond the noise |
| Code quality | Strict typing, 90%+ test coverage, no known vulnerabilities |
| Paid API spend for the whole project | Under $15, from real usage |
| Hosting | $0 |

## Milestones

Each one ends in a tagged release, a walkthrough, and a hard stop until Dan says go.

**M0 · Walking skeleton · 1 day · v0.1.0**
Tooling (uv, Python 3.11 to 3.15 in CI, Ruff, strict mypy, a coverage gate, Dependabot, a dependency audit, Claude Code hooks, decision notes). The suite format, version 1, validated with line-numbered errors. `temper validate` and `temper run` end to end on a scripted provider. Done when a five-case Dunder Mifflin suite runs offline in under five seconds and CI is green on every Python.

**M1 · Real runs, honest numbers · 1.5 days · v0.2.0**
A Claude provider, record and replay, and a fake for tests. A concurrency cap, retries with jittered backoff that are recorded, per-case time limits, a budget cap, and a dry-run cost estimate. Plumbing errors kept apart from answers; truncation and refusals labeled; the served model checked on every call; cost from real token usage; a full transcript per trial; resume after an interrupt. Risk check: a live run on five cases, under $0.50.

**M2 · Graders you can trust · 1.5 days · v0.3.0**
A plugin system for checks. An AI judge that scores one property at a time, treats answers as untrusted text, and is never the model under test. `temper label` and `temper calibrate` to measure the judge against Dan's labels. Risk check: a 30-answer judge pilot, about $1. If agreement stays under 90% after two revisions, the judge becomes advisory.

**M3 · Decisions, not dashboards · 2 days · v0.4.0**
Repeated trials with confidence intervals, paired comparisons, flaky-case detection, and a stated noise floor. `temper compare` with a ship-or-hold verdict. `temper doctor` to prove the wiring. A single-file HTML scorecard, accessible and light by default. A `--fail-on-regression` CI gate.

**M4 · The Dunder Mifflin story · 1 day · v0.5.0**
A 40-case support suite, and a second prompt, "Dwight's tidy-up," that quietly breaks refunds and lets a discount trick through. A pilot run confirms the regression clears the noise. The final recording is committed, so `temper demo` replays it for free, forever, and the scorecard goes live at temper.icarianforge.com.

**M5 · Launch · 1 day · v1.0.0**
A PyPI release through trusted publishing, a public repo, a quickstart, an architecture diagram, and the case study on icarianforge.com.

## Schedule and budget

Likely 8 working days, worst case 10, with a 2-day buffer. Expected API spend is about $8, capped at $15: a judge on Claude Opus 5.5 and a demo bot on Claude Sonnet 5.5, never the same model.

## Risks

| Risk | Mitigation | Trigger |
|---|---|---|
| The judge disagrees with Dan | Pilot it in M2; one property per check | Under 90% after two revisions: judge becomes advisory |
| The demo regression is lost in noise | Pilot before the paid recording | Error bars overlap: more trials or a sharper v2 |
| API spend creeps up | Dry-run estimates, a hard cap, prompt caching | Any run estimated over $5 needs Dan's OK |
| Model output breaks the report | Escaping, size caps, tests | Any unescaped output fails CI |
| An SDK or model changes mid-build | Lockfile, provider interface, recordings | A new major SDK release |
| Scope creep | Priorities with a clear cut line | Anything new waits until after v1.0 |
