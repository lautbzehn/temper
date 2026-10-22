# 0009 · The judge is a request like any other, and never the model under test

**Status:** Accepted · **v1.0 · 10.22.2026**

## Context
Some properties of an answer can't be decided in code: whether an apology blames the customer, whether a refusal stays polite. A second model can decide them, but a model's verdict is only worth something if it is asked carefully, costs what it says, can be replayed, and is measured against a person. A judge that is the model under test grades its own homework.

## Decision
A `judge` check names one property in plain words. The runner turns it into a `Request` with the suite's judge model, Temper's own system prompt, one user turn, and a JSON schema for the verdict, and sends it through the same pipe as an answer: the concurrency slot, the time limit, the budget, the retries, the served-model check, and the recording. The grade carries the verdict and what the call cost.

The user turn quotes the conversation and the answer inside tags, and puts the property after them, so the last thing the judge reads is the question and never the answer. Every tag ends in a hash of the quoted text, so a closing tag inside an answer is just text: to close its own tag, an answer would have to contain a hash of itself. The system prompt says so, says the quoted text is material to grade and not a message to it, that length, confidence, polish, and tone count only when the property names them, and that an empty answer, a refusal, or an answer to some other question fails. The verdict's JSON holds the reason first and the call second, so the judge reasons before it decides, and the grade is read by Pydantic, strictly, and never scraped out of prose.

The judge's model is set in the suite's `judge` block and defaults to `claude-opus-5-5`. The loader refuses a suite whose judge is the model under test, or a dated snapshot of it, when any check would use it.

A replay serves the verdicts its recording holds and asks the judge live for the rest. Answers are the thing under test and must not quietly change, so a changed answer is refused (0008); verdicts are the judge's and are meant to be revised, so a changed judge is tried on the same answers. A judge's completion that holds no verdict is never recorded: that is trouble with the judge, not a thing under test, and the judge is asked again next time.

## Consequences
- One property per call keeps each verdict about one thing, and makes a disagreement easy to read. A case with three properties costs three calls.
- The judge never sees the system prompt. It judges what the customer saw. A property that depends on policy has to say the policy.
- The judge's spend is counted apart from the answers', in the budget, the estimate, and the summary.
- A judge's verdict, however carefully asked, is an opinion until `temper calibrate` says how often it agrees with a person. Trust takes twenty labels, 90% agreement, and Cohen's kappa at 0.6, so a judge that agrees by always saying yes earns none. Each label names its answer by fingerprint and its property by wording, so the loop survives rewording and reordering. That loop is the point of this milestone.
