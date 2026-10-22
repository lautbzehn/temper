# 0010 · A check can reach no verdict, and that is not a failed check

**Status:** Accepted · **v1.0 · 10.22.2026**

## Context
Once a check can ask a model, a check can fail to get an answer: the judge is rate limited past the retries, cut off by `max_tokens`, refuses, or answers with something that isn't a verdict. A `cost` check meets a model with no list price. Writing any of that down as a failed check would score plumbing trouble as a wrong answer, the very thing 0006 forbids. Throwing the paid answer away would waste money and hide what did happen.

## Decision
A `Grade` has three states: `passed` is `True`, `False`, or `None`. `None` means the check reached no verdict, and `reason` says why, in words a person can act on. The trial is kept with its answer and its other grades, and goes into `results.jsonl` like any other.

A trial is scored only when its answer is complete and every one of its checks reached a verdict. The summary counts the trials left out "with no verdict" beside the truncated and refused ones, and the case's notes carry the reason.

## Consequences
- A judge outage lowers the number of scored trials and says so; it never lowers the pass rate.
- A `cost` check on an unpriced model is honest about not knowing, instead of passing or failing by accident.
- An unjudged trial stays unjudged in its run. A verdict that never came is never recorded, so a rerun with `--replay` replays the answers and asks the judge again for exactly those, which is cheaper than a new live run and keeps the labels valid.
