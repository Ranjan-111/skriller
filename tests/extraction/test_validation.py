import pytest

from skriller.extraction.validation import literal_value


@pytest.mark.parametrize(
    ("value", "quote", "expected"),
    [
        (25, "The company has 25 employees.", True),
        (25, "The company has 250 employees.", False),
        (25, "Revenue 25.5", False),
        (25, "Balance -25", False),
        (25, "Annual 25,000", False),
        (25, "count=25", True),
        ("alice@example.org", "Email alice@example.org", True),
        ("alice@example.org", "Email malice@example.org", False),
        ("alice@example.org", "Email alice@example.org.evil", False),
        ("Mira", "Miranda leads this team", False),
        ("Mira Rao", "Mira Rao founded the company", True),
        (True, "value true", True),
        (True, "value untrue", False),
        (float("nan"), "nan", False),
    ],
)
def test_whole_values_not_substring_proof(value, quote, expected):
    assert literal_value(value, quote) is expected
