# 0005 · Graders are validated models with a pure `grade`

**Status:** Accepted · **v1.0 · 10.21.2026**

## Context
Graders decide pass and fail, so they have to be predictable, easy to test, and easy to add. M2 will open them to plugins.

## Decision
- Each grader is a frozen Pydantic model. Its fields are its settings, validated when the suite loads, and unknown settings are rejected with a suggestion.
- `grade(answer)` is a pure function: same answer, same grade, no I/O. A `Grade` carries the check, the verdict, and a reason a person can read, like `never says "sorry"`.
- Graders are found by name in a registry, which M2 extends with entry points for plugins.
- Text comparisons ignore case (`str.casefold`) and collapse whitespace. Temper deliberately doesn't apply Unicode compatibility normalization (NFKC): it isn't stable when combined with case folding, and the simpler rule is one a person can predict.

## Consequences
- Property tests can state the graders' promises outright: `not_contains` is always the opposite of `contains`, normalizing twice changes nothing, and a text is found wherever it sits in an answer.
- A grader that needs I/O, like the AI judge in M2, will be async and live beside these, not inside them.
