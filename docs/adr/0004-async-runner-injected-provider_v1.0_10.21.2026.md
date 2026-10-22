# 0004 · An async runner, handed its provider

**Status:** Accepted · **v1.0 · 10.21.2026**

## Context
A real suite makes hundreds of model calls, each spending most of its time waiting on the network. Running them one at a time wastes minutes; running them all at once trips rate limits. And the runner has to work the same against a real model, a recording, or a script.

## Decision
- The runner is async from the first commit. Every case and trial becomes a task in an `asyncio.TaskGroup`, and a semaphore caps how many wait on the provider at once.
- Results are gathered in suite order, case by case and trial by trial, whatever order they finish in, so two runs of the same suite line up row for row.
- The runner doesn't choose its provider; it's handed one. `Provider` is a `Protocol` with a single `async complete(request)` method, so the fake provider, the coming Claude provider, and a test double are interchangeable without inheritance.

## Consequences
- Tests drive the runner with tiny providers that record timing and concurrency, with no network and no mocks of library internals.
- In M0 a provider error stops the whole run, and the CLI reports it from the `ExceptionGroup`. M1 changes that: plumbing failures will be kept as their own records instead of stopping the run.
