"""Small pieces of copy that several places print: counts and money, written for a person."""

from __future__ import annotations


def plural(count: int, noun: str) -> str:
    """`3 cases`, `1 case`."""
    return f"{count} {noun}{'' if count == 1 else 's'}"


def dollars(usd: float) -> str:
    """`$0.0031`: four places, since one answer costs a fraction of a cent."""
    return f"${usd:.4f}"


def percent(share: float) -> str:
    """`80%`: a share of one, to the nearest whole point."""
    return f"{share:.0%}"


def points(change: float) -> str:
    """`+5 points`, `-12 points`: a change between two shares, signed, to the nearest point."""
    whole = round(change * 100)
    return f"{whole:+d} {'point' if abs(whole) == 1 else 'points'}"


def gap(change: float) -> str:
    """`24 points`: the size of a change between two shares, unsigned."""
    whole = round(abs(change) * 100)
    return f"{whole} {'point' if whole == 1 else 'points'}"


def span(interval: tuple[float, float]) -> str:
    """`55 to 93%`: the ends of an interval of shares."""
    lower, upper = interval
    return f"{lower * 100:.0f} to {upper * 100:.0f}%"


def change_span(interval: tuple[float, float]) -> str:
    """`-32 to +19 points`: the ends of an interval of changes."""
    lower, upper = interval
    return f"{lower * 100:+.0f} to {upper * 100:+.0f} points"
