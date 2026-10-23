# 0013 · The scorecard escapes everything and loads nothing

**Status:** Accepted · **v1.0 · 10.23.2026**

## Context
A scorecard puts a model's answers on a page, and a model's answer is text nobody checked: it can hold `</td>`, `<script>`, or a prompt-injection aimed at whoever reads it. A report that a model's output can break, or that runs what a model wrote, is worse than no report. It also has to work years from now, offline, attached to an email or checked into a repository, and it has to say the same thing the terminal does.

## Decision
The page is one HTML file built from `markup.element` calls. Text is always escaped on the way in; only markup an `element` call made passes through. There is no template language, so there is no unescaped path to forget. A property test feeds arbitrary text in as an answer, a suite name, and a model name, reads the page back with Python's own HTML parser, and requires that every tag is on a short allowlist and every text reads back as itself.

The page loads nothing: no scripts, no fonts, no images, no network. A `Content-Security-Policy` of `default-src 'none'` with only inline styles allowed is set in the page itself, so even a mistake in escaping couldn't make it fetch or run anything. Every long text is clipped, saying how much more is in `results.jsonl`. The page holds no clock time of its own, only the run's, so the same run makes the same page byte for byte.

Every sentence on the page comes from `prose`, the same module the terminal report reads, so the two can't disagree. Colors are never the only signal: a regression says "worse beyond noise" in words, and the interval bars are hidden from screen readers, since the words beside them already say the range.

## Consequences
- No interactivity: no sorting, no filters. Opening a case uses `<details>`, which needs no script.
- Styles are inline in the page, which the policy allows. That costs nothing here, since nothing else can load.
- A very large suite makes a long page. Clipping keeps each answer bounded, but the page grows with cases times trials.
- Writing a new section means building it from `element` calls. That's slower than a template, and it's the point.
