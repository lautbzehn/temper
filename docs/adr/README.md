# Decision notes

Short records of the choices that shape Temper: the context, the decision, and what it costs. Newer notes refine older ones; nothing is deleted.

| # | Decision | Status |
|---|---|---|
| [0001](0001-python-311-and-uv_v1.0_10.21.2026.md) | Python 3.11 and up, managed with uv | Accepted |
| [0002](0002-suite-format-v1_v1.0_10.21.2026.md) | A strict YAML suite format, frozen at version 1 | Accepted |
| [0003](0003-errors-point-at-lines_v1.0_10.21.2026.md) | Every problem in one pass, each at its line | Accepted |
| [0004](0004-async-runner-injected-provider_v1.0_10.21.2026.md) | An async runner, handed its provider | Accepted |
| [0005](0005-graders-are-validated-models_v1.0_10.21.2026.md) | Graders are validated models with a pure `grade` | Accepted |
| [0006](0006-a-failure-is-never-a-wrong-answer_v1.0_10.22.2026.md) | A failed attempt is never a wrong answer | Accepted |
| [0007](0007-the-harness-owns-retries-budgets-and-models_v1.0_10.22.2026.md) | The harness owns retries, budgets, and the model it asked for | Accepted |
| [0008](0008-record-every-paid-run_v1.0_10.22.2026.md) | Every paid run is recorded, and a replay refuses a changed prompt | Accepted |
| [0009](0009-the-judge-is-a-request-like-any-other_v1.0_10.22.2026.md) | The judge is a request like any other, and never the model under test | Accepted |
| [0010](0010-a-check-can-reach-no-verdict_v1.0_10.22.2026.md) | A check can reach no verdict, and that is not a failed check | Accepted |
| [0011](0011-checks-are-plugins-through-entry-points_v1.0_10.22.2026.md) | Checks from other packages come through entry points, named by their class | Accepted |
| [0012](0012-every-rate-has-its-interval_v1.0_10.23.2026.md) | Every rate has its interval, and a verdict needs a change beyond noise | Accepted |
