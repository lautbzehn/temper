# Security

**v1.0 · 10.29.2026**

## Reporting a vulnerability

Please email **hello@icarianforge.com** with "Security" in the subject line. Do not open a public issue. Include what you found, how to reproduce it, and what an attacker could do with it. I aim to reply within a few days and will credit you if you'd like.

**In scope:** this repository, the `temper-evals` package on PyPI, and the demo scorecard at `temper.icarianforge.com`.

## How the project is protected

| Area | Control |
|---|---|
| Credentials | None in the repository. Temper reads Anthropic credentials from `ANTHROPIC_API_KEY` or `ant auth login`, and never takes a key as a command line option or from a suite file. |
| Publishing | PyPI releases go out through trusted publishing, so no PyPI token is stored anywhere. Only a published full release can publish, and the release job checks the tag matches the version and that the built wheel replays the demo before anything is uploaded. |
| The judge | The conversation and the answer reach the judge inside tags sealed with the answer's fingerprint, so an answer can't close a tag early and pass itself off as instructions. |
| Reports | The scorecard is one HTML file that loads nothing and runs nothing: no scripts, no fonts, no network. Every piece of text from a suite or a model is escaped on the way in, so an answer that contains markup is shown, never run. |
| The demo | `temper demo` replays a recording and is given no other provider, so it needs no key and can't reach the API. |
| Supply chain | Dependencies are locked in `uv.lock` and CI installs with `uv sync --locked`. `pip-audit --strict` checks the runtime dependencies on every change. Every GitHub Action is pinned to a commit, workflows get read-only repository access by default, and Dependabot watches `uv` and GitHub Actions weekly. |

## Your run folders

A run folder keeps every answer, verdict, and transcript the run bought, on your own machine. That's what makes replays and resumed runs free, and it also means a run folder is as sensitive as the prompts and cases in your suite. Keep it out of public repositories if your suite is private.

## Supported versions

Only the latest release on PyPI. Fixes ship as a new patch release.
