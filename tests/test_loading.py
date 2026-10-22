from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

from temper import SuiteError, load_suite
from temper.suite import Message
from tests.support import EXAMPLE

if TYPE_CHECKING:
    from pathlib import Path

    from tests.support import Files

REPLIES = 'case-one: "yes"\n'

VALID = textwrap.dedent("""
    schema: 1
    name: valid
    target:
      provider: fake
      options:
        replies: replies.yaml
    cases:
      - id: case-one
        input: Is this valid?
        checks:
          - type: contains
            text: "yes"
""").lstrip()


def problems(path: Path) -> list[tuple[int | None, str, str]]:
    """Each problem a suite file has, as (line, where, message)."""
    with pytest.raises(SuiteError) as caught:
        load_suite(path)
    return [(p.line, p.where, p.message) for p in caught.value.problems]


def test_the_example_suite_loads() -> None:
    suite = load_suite(EXAMPLE)

    assert suite.name == "dunder-mifflin-support"
    assert suite.trials == 3
    assert [case.id for case in suite.cases] == [
        "order-status",
        "paper-weight",
        "unopened-return",
        "discount-injection",
        "wet-paper-complaint",
    ]


def test_every_problem_is_reported_at_once_each_at_its_own_line(files: Files) -> None:
    files.write("replies.yaml", REPLIES)
    path = files.write(
        "suite.yaml",
        """
        schema: 1
        name: broken
        target:
          provider: fak
          options:
            replies: replies.yaml
        trails: 3
        cases:
          - id: Order Status
            input: Where is my order?
            checks:
              - type: contians
                text: "4471"
          - id: refund
            input: Refund?
            messages:
              - role: user
                content: Refund?
            checks:
              - type: contains
                text: no
          - id: complaint
            input: My paper is wet
        """,
    )

    assert problems(path) == [
        (4, "target.provider", "unknown provider 'fak'; did you mean 'fake'?"),
        (7, "trails", "unknown field; did you mean 'trials'?"),
        (
            9,
            "cases[0].id",
            "ids use lowercase letters, digits, '.', '-' and '_', and start with a letter or digit",
        ),
        (12, "cases[0].checks[0].type", "unknown check type 'contians'; did you mean 'contains'?"),
        (14, "cases[1]", "give exactly one of `input` or `messages`"),
        (
            21,
            "cases[1].checks[0].text",
            "expected text, but YAML read this as true or false; put it in quotes",
        ),
        (22, "cases[2]", "missing required field 'checks'"),
    ]


def test_the_error_reads_like_a_compiler_message(files: Files) -> None:
    files.write("replies.yaml", REPLIES)
    path = files.write("suite.yaml", VALID.replace("name: valid", "name: valid\ntrials: 0"))

    with pytest.raises(SuiteError) as caught:
        load_suite(path)

    assert str(caught.value) == f"{path}:3:1: trials: should be greater than 0"


def test_an_unreadable_file_is_a_problem_not_a_crash(tmp_path: Path) -> None:
    assert problems(tmp_path / "missing.yaml") == [
        (None, "", "can't read the file: No such file or directory")
    ]


def test_an_empty_file_says_so(files: Files) -> None:
    assert problems(files.write("suite.yaml", "")) == [(None, "", "the file is empty")]


def test_broken_yaml_points_at_the_line(files: Files) -> None:
    path = files.write("suite.yaml", "name: broken\ncases: [unclosed\n")

    [(line, where, message)] = problems(path)

    assert (line, where) == (3, "")
    assert message.startswith("this isn't valid YAML")


def test_a_file_that_is_not_a_mapping_is_rejected(files: Files) -> None:
    path = files.write("suite.yaml", "- just\n- a list\n")

    [(line, where, message)] = problems(path)

    assert (line, where) == (1, "")
    assert "dictionary" in message


def test_a_suite_needs_at_least_one_case(files: Files) -> None:
    files.write("replies.yaml", REPLIES)
    path = files.write("suite.yaml", VALID.split("cases:")[0] + "cases: []\n")

    assert problems(path) == [(7, "cases", "needs at least one entry")]


def test_case_ids_must_be_unique(files: Files) -> None:
    files.write("replies.yaml", REPLIES)
    again = (
        '  - id: case-one\n    input: Again?\n    checks:\n      - {type: contains, text: "yes"}\n'
    )

    assert problems(files.write("suite.yaml", VALID + again)) == [
        (7, "cases", "case ids must be unique; repeated: case-one")
    ]


def test_grader_settings_are_checked_with_suggestions(files: Files) -> None:
    files.write("replies.yaml", REPLIES)
    path = files.write("suite.yaml", VALID.replace('text: "yes"', 'txt: "yes"'))

    assert problems(path) == [
        (11, "cases[0].checks[0]", "missing required field 'text'"),
        (12, "cases[0].checks[0].txt", "unknown field; did you mean 'text'?"),
    ]


def test_provider_options_are_checked(files: Files) -> None:
    path = files.write("suite.yaml", VALID.replace("replies: replies.yaml", "replys: replies.yaml"))

    assert problems(path) == [
        (5, "target.options", "missing required field 'replies'"),
        (6, "target.options.replys", "unknown field; did you mean 'replies'?"),
    ]


def test_a_missing_replies_file_is_reported_on_the_options(files: Files) -> None:
    path = files.write("suite.yaml", VALID)

    [(line, where, message)] = problems(path)

    assert (line, where) == (5, "target.options")
    assert message.startswith("can't read fake replies")


def test_a_system_prompt_file_is_read_into_the_target(files: Files) -> None:
    files.write("replies.yaml", REPLIES)
    files.write("prompt.md", "You are the Dunder Mifflin support bot.\n")
    path = files.write(
        "suite.yaml", VALID.replace("provider: fake", "provider: fake\n  system_file: prompt.md")
    )

    target = load_suite(path).target

    assert target.system == "You are the Dunder Mifflin support bot.\n"
    assert target.system_file is None


def test_a_missing_system_prompt_file_is_reported(files: Files) -> None:
    files.write("replies.yaml", REPLIES)
    path = files.write(
        "suite.yaml", VALID.replace("provider: fake", "provider: fake\n  system_file: gone.md")
    )

    assert problems(path) == [(5, "target.system_file", "can't find 'gone.md'")]


def test_system_and_system_file_cannot_both_be_given(files: Files) -> None:
    files.write("replies.yaml", REPLIES)
    files.write("prompt.md", "Hello")
    text = VALID.replace("provider: fake", "provider: fake\n  system: Hi\n  system_file: prompt.md")

    assert problems(files.write("suite.yaml", text)) == [
        (3, "target", "give `system` or `system_file`, not both")
    ]


def test_input_is_one_user_turn_and_messages_pass_through(files: Files) -> None:
    files.write("replies.yaml", REPLIES)
    path = files.write(
        "suite.yaml",
        VALID.replace(
            "input: Is this valid?",
            "messages:\n      - role: user\n        content: Hi\n"
            "      - role: assistant\n        content: Hello\n"
            "      - role: user\n        content: Is this valid?",
        ),
    )
    plain = load_suite(files.write("plain.yaml", VALID)).cases[0]
    threaded = load_suite(path).cases[0]

    assert plain.conversation == (Message(role="user", content="Is this valid?"),)
    assert [m.role for m in threaded.conversation] == ["user", "assistant", "user"]


def test_a_broken_target_is_reported_once(files: Files) -> None:
    path = files.write("suite.yaml", VALID.replace("  provider: fake\n", ""))

    assert problems(path) == [(3, "target", "missing required field 'provider'")]


def test_a_check_without_a_type_is_reported_once(files: Files) -> None:
    files.write("replies.yaml", REPLIES)
    path = files.write("suite.yaml", VALID.replace("type: contains", "kind: contains"))

    assert problems(path) == [(11, "cases[0].checks[0]", "missing required field 'type'")]
