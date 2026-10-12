from decimal import Decimal

import pytest

from skriller.db.repositories import money


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "-0.01", "0.000000001", "1e100"])
def test_unbillable_numeric_values_are_rejected(value):
    with pytest.raises(ValueError):
        money(value)


def test_low_cost_usage_preserves_exact_eight_decimal_precision():
    assert money("0.00000001") == Decimal("0.00000001")
    assert money(0.01) == Decimal("0.01")
