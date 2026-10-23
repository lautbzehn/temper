# 0014 · The demo is a real recording, shipped and replayed

**Status:** Accepted · **v1.0 · 10.23.2026**

## Context
A tool that says when a difference is real needs a demo that is real too. A canned page or a scripted fake would show the layout and prove nothing. A live demo would cost money for every visitor, need a key, and change each time it ran. The story also has to keep telling the truth as the code changes around it.

## Decision
The story's suite, both prompts, and one live run with each ship inside the package under `temper/demo`. Each run was a plain `temper run`, five trials per case, and every paid run records itself (0008), so the pilot became the recording once it showed the regression clearing the noise.

`temper demo` replays both runs through the whole harness: the runner, the code checks, and the comparison. The recording is the only provider the replay is given, for the answers and for the judge, so nothing in the demo can reach the API by construction, not by luck: a trial whose request has changed (0008), or a verdict no longer on record (0009), is refused and written down as missing, never bought. A test replays the story and fails the build if any trial is missing or any check has no verdict. So a change to the suite, either prompt, or the judge's own prompt can't turn the demo into a live, paid run; it fails CI and says the story needs recording again.

The shipped copies of the recordings leave out the API's request ids, which identify the owner's own calls and which nothing replays.

## Consequences
- The package carries about 400 KB of recordings.
- Recording the story again costs about $2.30 at list price, and takes one live run per prompt. Any change to the judge's prompt requires it. A change to a judged property only needs that property judged again on the recorded answers, with `--replay`: after review, five checks were made stronger for $0.26, and one property was reworded when the judge read it more strictly than it meant, with both prompts judged on the same wording.
- The numbers are one sample of a model that varies. The careful prompt's 200 of 200 and the tidy-up's nine broken cases are what happened on one day, recorded, not a promise about every run.
- The judge's verdicts in the story weren't labeled by hand. The judge was calibrated against Dan's labels on the M2 pilot at 97% agreement, on different questions; a calibration on the story's own answers would make that claim stronger.
