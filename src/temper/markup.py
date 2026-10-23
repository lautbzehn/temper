"""Building HTML so that text can never become markup.

A page is put together from `element` calls. Text, whether from a suite, a
model, or anywhere else, is always escaped on the way in, and only markup an
`element` call made itself passes through as it is. So an answer that says
`</td><script>` is shown on the page, never run by it.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Final

# Elements that never have children or a closing tag.
_VOID: Final = frozenset({"meta", "br"})

Attribute = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class Markup:
    """HTML that `element` built, and so may be placed into a page as it is."""

    html: str


def element(tag: str, *children: Markup | str | None, **attributes: Attribute) -> Markup:
    """One element, its text children escaped and its markup children kept.

    Attribute names are written in Python's spelling: `class_` is `class`,
    and an underscore elsewhere is a hyphen, so `aria_hidden` is
    `aria-hidden`. True writes a bare attribute; None and False leave it out.
    A None child is nothing, so optional parts can sit inline.
    """
    opening = f"<{tag}{''.join(_attribute(name, value) for name, value in attributes.items())}>"
    if tag in _VOID:
        return Markup(opening)
    inner = "".join(_child(child) for child in children)
    return Markup(f"{opening}{inner}</{tag}>")


def join(*parts: Markup | str | None) -> Markup:
    """Several pieces side by side, as one, text escaped as always."""
    return Markup("".join(_child(part) for part in parts))


def _child(child: Markup | str | None) -> str:
    if child is None:
        return ""
    return child.html if isinstance(child, Markup) else escape(child, quote=False)


def _attribute(name: str, value: Attribute) -> str:
    if value is None or value is False:
        return ""
    spelled = name.removesuffix("_").replace("_", "-")
    if value is True:
        return f" {spelled}"
    return f' {spelled}="{escape(str(value), quote=True)}"'
