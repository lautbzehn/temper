from __future__ import annotations

from html.parser import HTMLParser

from hypothesis import given
from hypothesis import strategies as st

from temper.markup import Markup, element, join


class Reader(HTMLParser):
    """Reads a fragment back: its tags, its attributes, and its text."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str | None]] = []
        self.text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_data(self, data: str) -> None:
        self.text += data


def read(markup: Markup) -> Reader:
    reader = Reader()
    reader.feed(markup.html)
    reader.close()
    return reader


def test_text_is_escaped_and_markup_is_kept() -> None:
    built = element("p", "<b>bold</b> & more", element("em", "kept"))

    assert built.html == "<p>&lt;b&gt;bold&lt;/b&gt; &amp; more<em>kept</em></p>"


def test_attributes_are_spelled_for_html_and_escaped() -> None:
    built = element(
        "span", class_="bar", aria_hidden="true", title='say "hi" <now>', hidden=True, lang=None
    )

    assert built.html == (
        '<span class="bar" aria-hidden="true" title="say &quot;hi&quot; &lt;now&gt;" hidden></span>'
    )


def test_void_elements_have_no_closing_tag() -> None:
    assert element("meta", charset="utf-8").html == '<meta charset="utf-8">'


def test_nothing_is_nothing_and_parts_join() -> None:
    assert element("p", None, "a", None).html == "<p>a</p>"
    assert join(element("b", "x"), " & ", None).html == "<b>x</b> &amp; "
    assert element("p", disabled=False).html == "<p></p>"


@given(st.text())
def test_any_text_reads_back_as_itself_and_never_as_a_tag(text: str) -> None:
    reader = read(element("div", text, title=text))

    assert reader.tags == ["div"]
    assert reader.text == text
    assert reader.attributes == [("title", text)]
