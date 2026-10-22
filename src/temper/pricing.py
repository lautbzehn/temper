"""What a model's tokens cost, at Anthropic's list prices.

Prices are US dollars per million tokens, as published on the date below.
Cache writes are priced at the five-minute rate, the only kind Temper makes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from temper.providers.base import Usage

PRICED_ON: Final = "10.22.2026"


@dataclass(frozen=True, slots=True)
class Price:
    """Dollars per million tokens of each kind."""

    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:
        """Writing to the cache costs a quarter more than plain input."""
        return self.input * 1.25


PRICES: Final[Mapping[str, Price]] = {
    "claude-fable-5-1": Price(input=10.0, output=50.0, cache_read=0.25),
    "claude-opus-5-5": Price(input=4.0, output=20.0, cache_read=0.20),
    "claude-sonnet-5-5": Price(input=2.0, output=10.0, cache_read=0.20),
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_read=0.01),
}


def price_of(model: str) -> Price | None:
    """The price list entry for a model, if there is one.

    A dated snapshot such as `claude-opus-5-5-20260601` is priced as its
    family; anything the list doesn't know, like a fake, has no price.
    """
    if model in PRICES:
        return PRICES[model]
    family = next((name for name in PRICES if model.startswith(f"{name}-")), None)
    return PRICES[family] if family else None


def cost_usd(usage: Usage, model: str) -> float | None:
    """What `usage` costs on `model` at list price, or None when the model has no price."""
    price = price_of(model)
    if price is None:
        return None
    per_million = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    )
    return per_million / 1_000_000
