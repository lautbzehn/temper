# Temper quickstart

**v1.0 · 10.23.2026**

From nothing to a ship-or-hold call on your own prompt, in five steps.

## 1. See it work, with no key

```bash
uvx --from temper-evals temper demo
```

That replays a real recorded run of a support bot, before and after a prompt change that quietly breaks it, and writes `temper-demo.html`. It needs no key and costs nothing.

## 2. Install it

```bash
uv tool install temper-evals    # or: pipx install temper-evals, or: pip install temper-evals
temper --version
```

Temper needs Python 3.11 or newer. To call a real model, set `ANTHROPIC_API_KEY` in your environment, or sign in with `ant auth login`. Temper never reads a key from a file and never writes one down.

```bash
temper doctor    # checks Python, credentials, the models, and an offline run, and spends nothing
```

## 3. Write a suite

A suite is a YAML file: who answers, and what a good answer has to do. Save this as `suite.yaml`, and your bot's system prompt beside it as `support-bot.md`:

```yaml
schema: 1
name: my-support-bot

target:
  provider: claude
  model: claude-sonnet-5-5
  system_file: support-bot.md

trials: 5

cases:
  - id: unopened-return
    input: Can I return an unopened box for a refund?
    checks:
      - type: contains
        text: 30 days
      - type: judge
        property: offers a full refund for an unopened box returned within 30 days, which is the policy
```

Code checks (`contains`, `not_contains`, `equals`, `matches`, `length`, `json`, `cost`, `latency`) decide what code can. A `judge` check puts one property, in plain words, to a second model, Claude Opus 5.5 unless you name another. When a property depends on a policy, say the policy in the property: the judge sees what the customer saw, not your system prompt.

```bash
temper validate suite.yaml    # every problem at once, each at its line
```

## 4. Run it

```bash
temper run suite.yaml --dry-run      # what it could cost, at most; nothing is spent
temper run suite.yaml --budget 2     # the run, which never spends past the budget
```

Each run gets a folder under `runs/` with every request, answer, grade, and cost, and a recording that replays the run for free.

## 5. Compare two prompts, and gate a build on it

```bash
temper run suite.yaml                                   # the prompt you have
temper run suite.yaml --system support-bot-v2.md        # the prompt you'd like to ship
temper compare runs/<first> runs/<second> --fail-on-regression
temper scorecard runs/<second> --baseline runs/<first>  # one HTML page to share
```

`compare` sets each case against its twin, says whether each change is beyond noise, and makes the call: hold when anything got worse beyond noise, ship otherwise. With `--fail-on-regression` it exits 3 whenever the candidate can't ship, which is the CI gate. When a change is too small to tell at your number of trials, it says how many trials would settle it.

## Next

- Trust the judge: `temper label` and `temper calibrate` measure it against your own yes-or-no labels, and say whether it has earned trust.
- The [README](https://github.com/lautbzehn/temper/blob/main/README.md) has the whole tour, and the [architecture](https://github.com/lautbzehn/temper/blob/main/docs/architecture_v1.0_10.23.2026.md) shows how the pieces fit.
