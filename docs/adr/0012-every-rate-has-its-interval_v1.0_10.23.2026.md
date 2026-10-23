# 0012 · Every rate has its interval, and a verdict needs a change beyond noise

**Status:** Accepted · **v1.0 · 10.23.2026**

## Context
A pass rate from three trials looks like a number and isn't one, not yet. Teams compare 93% with 87% and ship, or hold, on a difference that two runs of the very same prompt would show by chance. Temper's reason to exist is to say when a difference is real, so every number it prints has to carry how sure it is, in a form a reader can hold up against a change.

## Decision
Every pass rate comes with a 95% Wilson score interval. Wilson behaves at the edges where small suites live: three of three is "likely 44 to 100%", not "100%". A change between two rates comes with Newcombe's interval, built from the two Wilson intervals, and the change is beyond noise only when that interval leaves zero behind. A run's noise floor is the half-width of the interval on the change between the run and its own twin: one number, in points, that any observed change can be held against.

Every trial of a case is taken as an independent draw of one chance, and the cases of a suite as the fixed set they are. A suite's rate pools its trials, which treats cases as alike; since cases differ, that pooled interval is wider than the stratified one, never narrower, so the error is on the honest side. A comparison sets each case against its twin, and the overall change is the pooled one.

The verdict holds for anything worse beyond noise, overall or on a single case, and ships otherwise. A case that went from three of three to none of three is beyond noise at three trials; two of three is not. When the overall change is undecided, the report says how many trials per case would settle a change of that size, found by searching the noise floor at growing sizes. Everything is closed form and standard library only.

## Consequences
- Small suites read as honest and rough: "likely 44 to 100%" is the truth about three trials, and the trials-to-tell line is the way out.
- Per-case regression flags at 95% will cry wolf now and then: at three trials and forty cases, about one false flag in six runs. At five trials the chance is negligible, which is what M4's pilot is for.
- The pooled interval is conservative, so a real but small overall improvement can read as undecided. The trials-to-tell line says what it would take.
- Flaky cases are named, not hidden: a case whose trials disagree is a case whose check or prompt needs attention before its rate means anything.
