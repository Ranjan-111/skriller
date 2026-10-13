from pathlib import Path

import pytest

from skriller.connectors.classification import classify_page

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/research"


def classify(html, **kwargs):
    return classify_page(
        html.encode(),
        source=kwargs.pop("source", "web"),
        final_url=kwargs.pop("url", "https://example.com"),
        **kwargs,
    )


@pytest.mark.parametrize(
    "fixture,status,next_method",
    [
        ("company.html", "readable", "extract"),
        ("challenge.html", "challenge", "stop"),
        ("dynamic.html", "js_shell", "dynamic"),
    ],
)
def test_collected_fixture_routes(fixture, status, next_method):
    result = classify((FIXTURES / fixture).read_text())
    assert result.status == status and result.next_method == next_method
    assert result.evidence_kind == ("page_read" if status == "readable" else "none")


@pytest.mark.parametrize(
    "source,url",
    [
        ("linkedin", "https://linkedin.com/authwall"),
        ("reddit", "https://reddit.com/login"),
        ("instagram", "https://instagram.com/accounts/login/"),
        ("x", "https://x.com/i/flow/login"),
    ],
)
def test_http200_platform_login_route_never_profile_evidence(source, url):
    result = classify("<html><body><h1>Welcome</h1></body></html>", source=source, url=url)
    assert result.status == "auth_required" and result.next_method == "connection"
    assert result.evidence_kind == "none"


def test_login_form_detected_without_relying_on_url():
    result = classify(
        '<html><head><title>Sign in</title></head><body><form><input type="password"><button>Sign in to continue</button></form></body></html>'
    )
    assert result.status == "auth_required" and result.next_method == "connection"


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><p>No results found</p></body></html>",
        '<html><body><main><p role="status">No posts found</p></main><script src="app.js"></script></body></html>',
    ],
)
def test_explicit_empty_results_is_not_js_shell_or_accepted_lead(html):
    result = classify(html)
    assert result.status == "empty_results" and result.next_method == "stop"
    assert result.evidence_kind == "empty_results"


def test_truly_empty_html_is_distinct_from_unrendered_app():
    assert classify("<html><body></body></html>").status == "empty"
    assert classify('<html><body><main id="root"></main></body></html>').status == "js_shell"


def test_existing_detectors_are_invoked(monkeypatch):
    calls = []

    def detect(body):
        calls.append(body)
        return True

    monkeypatch.setattr("skriller.connectors.classification._is_antibot_page", detect)
    result = classify("<p>Source</p>")
    assert result.status == "challenge" and result.reason == "copied_agent_reach_detector"
    assert len(calls) == 1


def test_actual_copied_scrapling_managed_challenge_detector():
    result = classify("<html><body><script>window.x={cType: 'managed'}</script></body></html>")
    assert result.status == "challenge" and result.reason == "copied_scrapling_detector"


def test_captcha_contact_form_and_security_article_are_readable():
    contact = '<html><body><h1>Aurora Ledger</h1><p>Public company information and contact form for Aurora Ledger.</p><script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script></body></html>'
    assert classify(contact).status == "readable"
    article = "<html><body><article><h1>Authentication design</h1><p>This article discusses the phrase sign in to view and how to implement a login form.</p></article></body></html>"
    assert classify(article).status == "readable"


@pytest.mark.parametrize(
    "status,expected",
    [(401, "auth_required"), (403, "access_denied"), (429, "rate_limited"), (503, "unavailable")],
)
def test_http_status_precedes_body(status, expected):
    assert classify("<h1>Aurora Ledger</h1>", status=status).status == expected


def test_hidden_empty_marker_and_empty_sidebar_do_not_override_visible_content():
    visible = '<html><body><h1>Aurora Ledger</h1><p>Our public company profile</p><div hidden><p role="status">No results found</p></div></body></html>'
    assert classify(visible).status == "readable"
    sidebar = '<html><body><article data-result="company"><h1>Aurora Ledger</h1></article><aside><p role="status">No posts found</p></aside></body></html>'
    assert classify(sidebar).status == "readable"


def test_password_gate_does_not_need_english_login_prompt():
    assert (
        classify(
            '<html><body><form><input type="password"><button>Continue</button></form></body></html>'
        ).status
        == "auth_required"
    )
