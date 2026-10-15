"""Execute the patched copied solver on controlled page transitions only."""

from types import SimpleNamespace

import pytest
from scrapling.engines._browsers import _stealth
from scrapling.engines._browsers._stealth import StealthySession
from scrapling.engines._browsers._validators import StealthConfig

from skriller.connectors.classification import classify_page


def solver_fixture(monkeypatch, *, clear):
    clock = [0.0]
    monkeypatch.setattr(_stealth, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        StealthySession, "_wait_for_networkidle", staticmethod(lambda *args, **kwargs: None)
    )
    monkeypatch.setattr(
        _stealth.ResponseFactory, "_get_page_content", staticmethod(lambda page: page.content())
    )
    session = object.__new__(StealthySession)
    session._config = SimpleNamespace(timeout=1500 if clear else 100)

    class Page:
        def set_default_timeout(self, timeout):
            assert 0 < timeout <= session._config.timeout

        set_default_navigation_timeout = set_default_timeout

        def wait_for_timeout(self, milliseconds):
            clock[0] += milliseconds / 1000

        def wait_for_load_state(self, *, timeout):
            assert timeout > 0

        def content(self):
            if clear and clock[0] >= 1:
                return "<html><body><h1>Controlled company page</h1></body></html>"
            return "<html><script>cType: 'non-interactive'</script></html>"

    return session, Page(), clock


def test_copied_solver_returns_only_a_cleared_controlled_page(monkeypatch):
    solver, page, clock = solver_fixture(monkeypatch, clear=True)
    assert (
        classify_page(page.content().encode(), source="web", final_url="https://example.com").status
        == "challenge"
    )
    solver._cloudflare_solver(page)
    assert clock[0] == 1
    final = classify_page(page.content().encode(), source="web", final_url="https://example.com")
    assert final.accepts_content and "Controlled company page" in page.content()


def test_persistent_copied_challenge_exits_at_the_shared_deadline(monkeypatch):
    solver, page, clock = solver_fixture(monkeypatch, clear=False)
    with pytest.raises(TimeoutError, match="deadline"):
        solver._cloudflare_solver(page)
    assert clock[0] <= 0.101
    assert not classify_page(
        page.content().encode(), source="web", final_url="https://example.com"
    ).accepts_content


def test_copied_config_cannot_expand_the_callers_timeout():
    assert StealthConfig(timeout=250, solve_cloudflare=True).timeout == 250
