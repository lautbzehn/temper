# 0014 · The demo is a real recording, shipped and replayed

**Status:** Accepted · **v1.0 · 10.23.2026**

## Context
A tool that says when a difference is real needs a demo that is real too. A canned page or a scripted fake would show the layout and prove nothing. A live demo would cost money for every visitor, need a key, and change each time it ran. The story also has to keep telling the truth as the code changes around it.

## Decision
The story's suite, both prompts, and one live run with each ship inside the package under `temper/demo`. Each run was a plain `temper run`, five trials per case, and every paid run records itself (0008), so the pilot became the recording once it showed the regression clearing the noise.

`temper demo` replays both runs through the whole harness: the runner, the retries and the budget, the code checks, and the comparison. Answers come from the recording, which refuses any trial whose request has changed (0008), and so do verdicts (0009). It needs no key, because nothing is asked of the API when everything is on record. A test replays the story and fails the build if any trial is missing, any check has no verdict, or anything was spent. So a change to the suite, either prompt, or the judge's own prompt can't quietly turn the demo into a live, paid run; it fails CI and says the story needs recording again.

## Consequences
- The package carries about 400 KB of recordings.
- Recording the story again costs about $2.30 at list price, and takes one live run per prompt. Any change to the judge's prompt requires it.
- The numbers are one sample of a model that varies. The careful prompt's 200 of 200 and the tidy-up's nine broken cases are what happened on one day, recorded, not a promise about every run.
- The judge's verdicts in the story weren't labeled by hand. The judge was calibrated against Dan's labels on the M2 pilot at 97% agreement, on different questions; a calibration on the story's own answers would make that claim stronger.
