# 0003 · Every problem in one pass, each at its line

**Status:** Accepted · **v1.0 · 10.21.2026**

## Context
Pydantic's errors say *what* is wrong and *where in the data*, but YAML loaders throw away line numbers. A tool that says "field required" without a line makes people hunt. And a tool that stops at the first problem makes people fix, rerun, fix, rerun.

## Decision
The loader parses the file once with PyYAML's composer, keeping both the data and a map from each location (`("cases", 2, "checks", 0)`) to where it starts. Any error, from Pydantic or from Temper's own checks, is placed at the nearest location the file actually has, and written as `file:line:column: where: message`. The suite's shape, its checks, and its target are checked independently, so a typo in one place never hides a mistake in another. Messages are rewritten in plain words. An unknown field gets a "did you mean" drawn only from the fields allowed at that spot, or, when it's a real field that belongs elsewhere, where it goes. YAML's traps get named: `no` read as false, `4471` read as a number, and a key given twice, which YAML would otherwise resolve by silently keeping the last.

## Consequences
- No extra dependency: PyYAML already keeps the marks; Temper just doesn't throw them away.
- Error wording is Temper's own, so it's tested like any other output.
- A list whose items all fail also reports being too short. The loader drops that echo when the items' own errors already explain it.
