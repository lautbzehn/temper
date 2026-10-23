# 0012 · Every rate has its interval, and a verdict needs a change beyond noise

**Status:** Accepted · **v1.0 · 10.23.2026**

## Context
A pass rate from three trials looks like a number and isn't one, not yet. Teams compare 93% with 87% and ship, or hold, on a difference that two runs of the very same prompt would show by chance. Temper's reason to exist is to say when a difference is real, so every number it prints has to carry how sure it is, in a form a reader can hold up against a change.

## Decision
Every pass rate comes with a 95% Wilson score interval. Wilson behaves at the edges where small suites live: three of three is "likely 44 to 100%", not "100%". A change between two rates comes with Newcombe's interval, built from the two Wilson intervals, and the change is beyond noise only when that interval leaves zero behind. A run's noise floor is the smallest change from its rate, either way, whose interval would leave zero behind at this size: one number, in points, with the property that a change under it is never called real. At one or two trials no change could be, and the floor says so instead of printing a number.

Every trial of a case is taken as an independent draw of one chance, and the cases of a suite as the fixed set they are. A suite's rate pools its trials, which treats cases as alike; since cases differ, that pooled interval is wider than the stratified one, never narrower, so the error is on the honest side. A comparison sets each case against its twin, and the overall change is the pooled one.

A comparison judges one change per case, and forty cases are forty chances for a false alarm, so each case's interval is widened so that one false alarm among all the cases is as unlikely as one alone, in the manner of Bonferroni. The overall change stands on its own at 95%. The verdict holds for anything worse beyond noise, overall or on a single case; makes no call when a case has nothing scored in either run, since an empty table is not a pass; and ships otherwise. When the overall change is undecided, the report says how many trials per case would settle a change of that size, found by searching for the size at which the change's own interval leaves zero behind. Everything is closed form and standard library only, and the search costs nothing.

## Consequences
- Small suites read as honest and rough: "likely 44 to 100%" is the truth about three trials, and the trials-to-tell line is the way out.
- The widening has a price in trials. Among forty cases, three of three to none of three can't hold the build; five of five to none of five can, and five of five to one of five can't. Computed exactly from the rule and the binomial, the chance that a candidate identical to its baseline is held on some case out of forty is at most 5% at any pass rate and size (3.8% at five trials and a 50% rate, 0.4% at 80%, nothing at 90%). Without the widening it would be 54% at five trials and an 80% rate, and 71% at 50%: more holds than not.
- Pooling a suite's trials errs wide because p(1 - p) is concave, so the pooled variance is at least the stratified one. Wide is the lenient side for a hold: the overall change has less power against a diffuse drift across many cases, and only the per-case flags, or more trials, catch that. The trials-to-tell line says what it would take.
- Flaky cases are named, not hidden: a case whose trials disagree is a case whose check or prompt needs attention before its rate means anything.
- Two runs judged by different models still compare, since the cases are the same, but the report says so first: the change may be the judge's.
