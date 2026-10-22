from __future__ import annotations

import pytest

from temper.pricing import PRICES, cost_usd, price_of
from temper.providers import Usage


def test_a_known_model_is_priced() -> None:
    assert price_of("claude-sonnet-5-5") is PRICES["claude-sonnet-5-5"]


def test_a_dated_snapshot_is_priced_as_its_family() -> None:
    assert price_of("claude-opus-5-5-20260601") is PRICES["claude-opus-5-5"]


@pytest.mark.parametrize("model", ["fake", "claude-sonnet-5-50", "claude-opus"])
def test_an_unknown_model_has_no_price(model: str) -> None:
    assert price_of(model) is None
    assert cost_usd(Usage(input_tokens=1_000_000), model) is None


def test_cost_adds_up_each_kind_of_token() -> None:
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_read_tokens=1_000_000,
        cache_write_tokens=1_000_000,
    )

    assert cost_usd(usage, "claude-sonnet-5-5") == pytest.approx(2.0 + 1.0 + 0.20 + 2.5)


def test_cache_writes_cost_a_quarter_more_than_input() -> None:
    assert PRICES["claude-opus-5-5"].cache_write == pytest.approx(5.0)
