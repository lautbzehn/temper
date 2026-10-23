# Temper: a case study

**v1.0 · 10.23.2026 · Draft for Dan's review, written in his voice**

## The problem

Teams that build on AI change a prompt or a model every week, and most of them can't say whether the change made things better, worse, or just different. An answer that passed yesterday fails today for no reason anyone changed. A spreadsheet of pass rates from three tries of each question looks like evidence and isn't. I wanted a tool that tests AI features the way we test code, and tells you, in plain words, when a difference is real.

## What I built

Temper is a Python library and command line. You write a suite of questions and what a good answer has to do, and Temper asks each one several times, grades every answer, and keeps an honest record: a timeout is never written down as a wrong answer, every number comes with how sure it is, and two runs end in a call to ship or to hold. Where code can't decide, a second model judges, and that judge is measured against my own labels before its verdicts are believed.

The demo tells the whole story. A support bot for Dunder Mifflin answers 40 customer questions, five times each, with its careful prompt. Then Dwight tidies the prompt up: half as long, and it quietly changes two rules. The careful prompt passed all 200 trials. The tidy version broke nine cases, refunds steered to store credit and discounts honored because a customer said an employee promised one, and Temper holds it. The obvious attack, a message shouting "SYSTEM OVERRIDE", failed against both. The polite, plausible one got through. You can replay the whole thing in five seconds, for free, with no key.

## How I built it with Claude Code

I set the goal before the first line of code: the code itself is the product, and it should impress anyone who reads it. That went into the project's instructions as a quality bar every change has to meet: small modules with one job each, full typing, every lint rule on, and tests covering every line and branch. A hook checks every file the moment it's edited, so nothing slips past for later.

I worked in milestones, six of them over three days, each ending in a release and a hard stop where I read a walkthrough and said go. I chose the model for each task: the most capable one for the subtle parts, like the async runner and the statistics, and a faster one for building, writing, and chores. Before every milestone closed, a separate model read the whole change cold, as a reviewer would, and its findings were fixed before I saw the pull request.

## What the checks caught

The most useful thing about the process was how much it caught before it mattered.

- **The first live run found a bug the tests couldn't.** Every trial's first attempt failed, and the retry quietly succeeded. The retry log Temper keeps made it visible; the cause was one connection pool shared across two event loops. It shipped as a patch the same day, with a test against a real socket.
- **My own labeling found two more.** The labeling screen cropped long answers, and a `#` in a question had turned the rest of the line into a YAML comment, so the bot had been asked "Where is order" and nothing more.
- **Looking at the scorecard found a statistics bug.** A broken case's interval showed as a single point. Newcombe's formula had its two sides swapped, which only shows when two rates differ. It now matches his published worked examples to four places.
- **The reviews found the honesty holes.** A candidate that answered nothing at all would have shipped. A per-case check would have held an unchanged prompt more often than not across forty cases. A demo was offline only because its recording happened to be complete. Each was fixed, with a test that fails if it comes back.

## By the numbers

| | |
|---|---|
| Releases | 7, from v0.1.0 to v0.5.0, then v1.0.0 |
| Tests | 362, covering every line and branch on Python 3.11 through 3.15 |
| Code | 33 modules, about 2,500 statements, strict typing throughout |
| Decision notes | 14, each with what the choice costs |
| Judge agreement with my labels | 29 of 30 (97%), kappa 0.65 |
| API spend for the whole project | about $3, against a $15 cap |

## What I'd say about it

Temper is small, and it's honest about what it doesn't know. Three trials of a question is "likely 44 to 100%", not "100%". A judge has to earn trust against a person's labels. A demo is a real recording with its costs stated. That's the standard I want for any AI feature I ship, and building the tool that holds me to it, with Claude Code, showed me how much faster careful work goes when every step is checked.

[Links: the repository, the live demo, PyPI.]
