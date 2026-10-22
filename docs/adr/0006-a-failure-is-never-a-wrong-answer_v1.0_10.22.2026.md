# 0006 · A failed attempt is never a wrong answer

**Status:** Accepted · **v1.0 · 10.22.2026**

## Context
Most homemade eval harnesses quietly mix plumbing with judgment. A timeout, a rate limit, or a crash lands in the same column as a wrong answer, so the pass rate drops for reasons that have nothing to do with the model, and nobody can tell. A cut-off answer gets scored as wrong when the only thing wrong was the token cap. A refusal gets summed in with mistakes.

## Decision
Every (case, trial) ends as exactly one of two records, and they never share a file:

- An **answered trial** in `results.jsonl`: the request, the completion with its status (`complete`, `truncated`, or `refused`), the usage and its cost at list price, the latency of the final request alone, the attempt count with every retry, and every grade.
- A **failure** in `errors.jsonl`: the kind (`timeout`, `provider`, `served-model`, or `budget`), the reason in plain words, how many attempts were made and every retry among them, and what it cost when that is known. A failure is a missing answer, not a wrong one.

Pass rates are drawn from complete answers only. Truncated and refused answers are graded, since they are things the model did, but reported as their own counts. Every answer is checked to have come from the model that was asked for; any other model fails the attempt.

The run folder is written as the run happens, so an interrupted run keeps every answer it got. `temper resume` answers only the slots that have no answer; failures stay in the file as history. `temper run` exits 2 while any slot is unanswered, and says how to pick it up.

## Consequences
- The numbers describe the model. "Incomplete" and "bad" are different states, and the summary says which.
- Three files per run instead of one, and a summary with more to say. Both are the point.
- A resumed run reports its earlier failures alongside the answers that eventually came, so the history is never tidied away.
