# 0008 · Every paid run is recorded, and a replay refuses a changed prompt

**Status:** Accepted · **v1.0 · 10.22.2026**

## Context
A demo, a test suite, and a CI job should not spend money or need the network. But a replayed score is only honest if it describes the prompt that actually ran, and prompts change.

## Decision
A run that charges writes `recording.jsonl` beside its results: for each (case, trial), a fingerprint of what was sent (the model, the system prompt, the messages, and `max_tokens`) and the completion that came back. A replay, asked for with `--replay` or a `provider: replay` target, answers from that file and nothing else. A trial that was never recorded is refused. A trial whose fingerprint no longer matches is refused too, with a message that says to run the suite live again.

Replayed answers carry their recorded usage, so the summary can say what the run would have cost at list price, and that nothing was spent.

## Consequences
- A committed recording keeps the public demo at no cost, for as long as the prompt stays the same.
- Any edit to a prompt, a model, or `max_tokens` means recording again. That friction is deliberate.
- A recording holds the model's answers in full, so demo data stays fictional.
