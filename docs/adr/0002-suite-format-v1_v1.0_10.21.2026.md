# 0002 · A strict YAML suite format, frozen at version 1

**Status:** Accepted · **v1.0 · 10.21.2026**

## Context
A suite file is where people spend their time with Temper. It needs to be easy to write by hand, easy to review in a pull request, and hard to get quietly wrong.

## Decision
- Suites are YAML, which reads well and diffs cleanly.
- Every model is closed to unknown fields, so `trails: 3` is an error with a suggestion, not a silently ignored typo.
- Counts are read as written: `trials: yes` or `trials: "3"` is an error, not a quiet conversion to a number.
- Each check names its grader explicitly, `type: contains`, and everything else in the check belongs to that grader. That keeps the suite format small and lets graders, including future plugins, own their settings.
- A case asks with exactly one of `input` or `messages`. A target takes exactly one of `system` or `system_file`.
- `schema: 1` is required and frozen against breaking changes. New optional fields may arrive; nothing a valid suite says today will stop meaning what it means.

## Consequences
- Some friction up front: a misspelled field fails loudly. That's the point.
- When a breaking change is truly needed, it gets `schema: 2` and a loader that still reads version 1.
