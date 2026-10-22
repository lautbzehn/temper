"""Small pieces of copy that several places print: counts and money, written for a person."""

from __future__ import annotations


def plural(count: int, noun: str) -> str:
    """`3 cases`, `1 case`."""
    return f"{count} {noun}{'' if count == 1 else 's'}"


def dollars(usd: float) -> str:
    """`$0.0031`: four places, since one answer costs a fraction of a cent."""
    return f"${usd:.4f}"
