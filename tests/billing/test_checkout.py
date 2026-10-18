import pytest

from skriller.billing.checkout import CheckoutConfiguration


@pytest.mark.parametrize(
    "origin", ["http://localhost:3000", "https://skriller.example", "https://app.example:443"]
)
def test_checkout_accepts_only_server_configured_web_origins(origin):
    assert CheckoutConfiguration("skriller-fixture", origin).return_origin == origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://public.example",
        "https://user:pass@site.example",
        "https://site.example/path",
        "https://site.example?q=1",
        "https://site.example#token",
        "https://site.example\\evil",
        "https://evil.example\n",
        "javascript:alert(1)",
        "https://site.example:99999",
    ],
)
def test_checkout_rejects_unsafe_or_non_origin_return_configuration(origin):
    with pytest.raises(ValueError):
        CheckoutConfiguration("skriller-fixture", origin)
