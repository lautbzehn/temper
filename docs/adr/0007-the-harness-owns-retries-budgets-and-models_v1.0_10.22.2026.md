# 0007 · The harness owns retries, budgets, and the model it asked for

**Status:** Accepted · **v1.0 · 10.22.2026**

## Context
The Anthropic SDK is helpful by default: it retries on its own, and it can be told to fall back to another model when one declines. Both hide things an eval has to see. A retry the harness doesn't know about disappears from the record; a fallback quietly measures a different model than the one named in the suite.

## Decision
- The SDK's retries are turned off (`max_retries=0`). Temper retries transient trouble itself: rate limits, `408`, `409`, server errors, and network failures, with a doubling delay, full jitter, a 30-second cap, and the API's own `retry-after` when it gives one. Every retry is written on the result.
- Each trial has a time limit that covers all of its retries, and it runs inside the concurrency slot, so waiting in line never counts against a trial.
- A budget reserves each request's worst case before it is sent: the counted input tokens plus the whole `max_tokens` of output, at list price. A run can stop short of its budget; it cannot pass it. A request cut off before it answered is counted at its worst case, since the API may well have billed it. A budget on a model with no list price is refused up front, since nothing could be reserved, and a provider that answers for free has nothing to budget.
- No fallback is ever sent. If the model that answered isn't the one asked for, allowing a dated snapshot of it, the attempt fails and says so.
- Credentials come from the environment, never from a file Temper reads or writes. A run that charges begins with one free `count_tokens` call, which proves the credentials and the model before any money is spent, and before the run's folder exists. If that fails, nothing is kept.

## Consequences
- More code than letting the SDK retry, in exchange for a complete record of what happened.
- A dry run reports the worst case honestly, which is usually well above what a run really costs.
- A suite can be validated and replayed with no credentials at all; only a paid run needs them.
