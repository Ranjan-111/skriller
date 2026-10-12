import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("search_probe", ROOT / "scripts/probes/search.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def payload(domain="linkedin.com", applied=True):
    return {
        "query": {
            "search_operators": {"applied": applied, "sites": [domain]},
            "more_results_available": True,
        },
        "web": {"results": [{"url": f"https://www.{domain}/company/example", "title": "Example"}]},
    }


@pytest.mark.parametrize("live,key", [(False, "secret"), (True, None)])
def test_no_implicit_search_or_provider_fallback(live, key):
    def forbidden(**kwargs):
        pytest.fail("No authorised live operation")

    report = module.probe(live=live, api_key=key, caller=forbidden)
    assert report["status"] == "skipped"
    assert report["validated"] is False
    assert report["requests_attempted"] == 0
    assert report["google_backend"] is False


def test_ignored_domain_operator_cannot_advertise_constrained_search():
    page, _urls = module.measure_page(payload("evil.test", applied=False), "linkedin.com")
    assert page["off_domain_results"] == 1
    assert page["domain_constraint_observed"] is False


def test_lookalike_domain_and_private_results_do_not_validate_operator():
    data = payload()
    data["web"]["results"] = [
        {"url": "https://linkedin.com.evil.test/in/person"},
        {"url": "http://127.0.0.1/private"},
    ]
    page, urls = module.measure_page(data, "linkedin.com")
    assert page["invalid_urls"] == 1
    assert page["off_domain_results"] == 1
    assert page["domain_constraint_observed"] is False
    assert len(urls) == 1


def test_fixed_corpus_pagination_duplicates_and_cost_are_measured_without_raw_results():
    calls = []

    def caller(**kwargs):
        calls.append(kwargs)
        domain = "reddit.com" if "reddit.com" in kwargs["query"] else "linkedin.com"
        return payload(domain)

    report = module.probe(live=True, api_key="secret", caller=caller)
    assert len(calls) == 6
    assert [call["offset"] for call in calls] == [0, 1, 0, 1, 0, 1]
    assert report["queries"][0]["duplicate_rate"] == 0.5
    assert report["nominal_list_price_estimate_usd"] == "0.030"
    assert report["observed_billed_cost_usd"] is None
    assert report["coverage_complete"] is False
    assert report["domain_constrained_search_advertisable"] is True
    assert report["raw_results_persisted"] is False
    assert "secret" not in json.dumps(report)
    assert "https://www.linkedin.com/company/example" not in json.dumps(report)


def test_empty_results_do_not_prove_domain_operator_support():
    data = payload()
    data["web"]["results"] = []
    page, _urls = module.measure_page(data, "linkedin.com")
    assert page["domain_constraint_observed"] is False


def test_failure_redacts_key_and_provider_payload():
    def fail(**kwargs):
        raise RuntimeError("secret and provider response")

    report = module.probe(live=True, api_key="secret", caller=fail)
    assert report["status"] == "failed"
    assert report["validated"] is False
    assert "secret" not in json.dumps(report)
    assert report["requests_attempted"] == 1


@pytest.mark.parametrize(
    "query,count,offset",
    [("", 10, 0), ("x" * 601, 10, 0), ("x " * 76, 10, 0), ("valid", 21, 0), ("valid", 10, 10)],
)
def test_provider_bounds(query, count, offset):
    with pytest.raises(ValueError):
        module.validate_request(query, count, offset)


@pytest.mark.live
def test_controlled_live_search_corpus():
    key = os.environ.get("SKRILLER_BRAVE_API_KEY")
    if not key:
        pytest.skip("Brave API key unavailable; provider quality has not been measured")
    report = module.probe(live=True, api_key=key)
    assert report["status"] == "measured", report["reason"]
    assert report["requests_attempted"] == 6


def test_actual_client_uses_fixed_endpoint_header_key_and_bounded_provider_parameters(monkeypatch):
    original_client = module.httpx.Client
    observed = []

    def respond(request):
        observed.append(request)
        return module.httpx.Response(200, json=payload())

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: original_client(**kwargs, transport=module.httpx.MockTransport(respond)),
    )
    assert (
        module.fetch_page(
            query='site:linkedin.com "fintech"', count=10, offset=1, country="IN", api_key="secret"
        )
        == payload()
    )
    request = observed[0]
    assert str(request.url).startswith(module.ENDPOINT + "?")
    assert "secret" not in str(request.url)
    assert request.headers["X-Subscription-Token"] == "secret"
    assert request.url.params["operators"] == "true"
    assert request.url.params["spellcheck"] == "false"
    assert request.url.params["offset"] == "1"


def test_client_refuses_redirects_instead_of_forwarding_credentials(monkeypatch):
    original_client = module.httpx.Client
    observed = []

    def respond(request):
        observed.append(request)
        return module.httpx.Response(302, headers={"Location": "https://evil.test/key"})

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: original_client(**kwargs, transport=module.httpx.MockTransport(respond)),
    )
    with pytest.raises(module.httpx.HTTPStatusError):
        module.fetch_page(query="fintech", count=10, offset=0, country="IN", api_key="secret")
    assert len(observed) == 1


def test_success_status_error_payload_is_not_measured_as_empty_search():
    with pytest.raises(TypeError):
        module.measure_page({"error": {"message": "not search results"}}, "linkedin.com")
