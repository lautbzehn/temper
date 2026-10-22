# 0001 · Python 3.11 and up, managed with uv

**Status:** Accepted · **v1.0 · 10.21.2026**

## Context
Temper is meant to show modern Python, and it leans on concurrency from day one. Python 3.10 reached end of life on 10.01.2026; 3.15 shipped on 10.09.2026.

## Decision
Support Python 3.11 through 3.15, and test every one of them in CI. 3.11 is the floor because it brings `asyncio.TaskGroup`, `ExceptionGroup` and `except*`, and `typing.Self`, which the runner and models use directly. uv manages Python versions, the lockfile, and the build (`uv_build`), so a fresh clone needs one tool and one command: `uv sync`.

## Consequences
- Anyone on a supported Python can use Temper; nobody on an unsupported one is promised anything.
- `typing.override` arrived in 3.12, so it comes from `typing_extensions` until 3.11 leaves support.
- Contributors need uv. That's a small ask, and the README says so up front.
