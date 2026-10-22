# 0011 · Checks from other packages come through entry points, named by their class

**Status:** Accepted · **v1.0 · 10.22.2026**

## Context
Nine built-in checks cover text, shape, cost, speed, and judgment, but a team's own rules (a JSON Schema, a banned-phrase list, a domain lookup) belong to the team. Temper should take them without a fork, and without a dependency on every library such a check might want.

## Decision
A check is a `Grader` subclass: a Pydantic model whose fields are its settings, a `name` class variable, and a pure `grade(answer)`. A package registers one under the `temper.graders` entry point group. Temper loads the group once, checks that each entry is a `Grader` with a string `name` that isn't already taken, and adds it to the registry the loader and the runner share, so a plugin check validates at load time with line numbers like a built-in one.

The entry point's own name is only a label. The check's `type` is the class's `name`, so there is one source of truth and no way to register a class under two names.

The loader is generic: it loads a group and reports what it found with the plugin's name and package. The graders module decides what counts as a grader. A plugin that can't be imported, isn't a grader, has no name, or takes a taken name is a `PluginError` that names the package, raised when checks are first needed, so `temper --version` never fails over someone else's bug.

## Consequences
- A JSON Schema check is a ten-line plugin with `jsonschema` as its own dependency; Temper stays light.
- Plugins are found through installed metadata, so the tests install a pretend package into a temporary folder rather than mocking the discovery.
- Only code checks can be plugged in. The judge is the one check that asks a model, and its honesty rules (0009) stay Temper's.
- Every suite's checks are validated against the one registry, so a broken plugin stops every suite from loading until it is fixed or uninstalled. The error names the plugin and its package, which is the right place to look.
