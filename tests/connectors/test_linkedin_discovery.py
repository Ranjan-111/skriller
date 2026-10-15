import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from skriller.connectors.linkedin_discovery import LinkedInSearch, parse_search_response

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def response(request, **changes):
    return {
        "url": request.search_url(),
        "sections": {"search_results": "Search page text"},
        "references": {
            "search_results": [
                {
                    "kind": "person",
                    "url": "https://www.linkedin.com/in/synthetic/",
                    "text": "Example",
                },
                {
                    "kind": "feed_post",
                    "url": "https://www.linkedin.com/feed/update/urn:li:activity:12345/",
                },
            ]
        },
        **changes,
    }


def test_copied_url_and_reference_modules_retain_recorded_hashes():
    root = Path(__file__).resolve().parents[2]
    target = root / "src/skriller/_vendor/linkedin"
    provenance = json.loads((target / "PROVENANCE.json").read_text())
    assert provenance["commit"] == "f1ba6aa87234526cf22812e59233e0c619073529"
    for name, record in provenance["files"].items():
        assert hashlib.sha256((target / name).read_bytes()).hexdigest() == record["sha256"]
        source = root / "third_party/external/linkedin" / record["source"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == record["source_sha256"]


def test_people_filters_use_actual_copied_grammar_and_bounded_tool_arguments():
    request = LinkedInSearch(
        operation="search_people",
        keywords="founder",
        location="London",
        network=["F"],
        current_company="12345",
    )
    assert "currentCompany=" in request.search_url() and "network=" in request.search_url()
    assert request.backend_arguments() == {
        "keywords": "founder",
        "location": "London",
        "network": ["F"],
        "current_company": "12345",
    }
    page = parse_search_response(response(request), request, observed_at=NOW)
    assert page.status == "parsed_not_live_verified" and not page.pagination_supported
    assert all(item.subject_identity == "unknown" for item in page.references)


def test_post_filters_are_one_bounded_page_and_links_are_not_aligned_to_authors():
    request = LinkedInSearch(operation="search_posts", keywords="hiring", date_posted="past_week")
    assert request.backend_arguments()["max_pages"] == 1
    page = parse_search_response(response(request), request, observed_at=NOW)
    assert {item.kind for item in page.references} == {"person", "feed_post"}
    assert not any("author" in item.model_dump() for item in page.references)


def test_dropped_filter_or_wrong_source_url_is_rejected_before_readiness():
    request = LinkedInSearch(operation="search_people", keywords="founder", location="London")
    for url in (
        "https://www.linkedin.com/search/results/people/?keywords=founder",
        "https://linkedin.com.evil.example/search/results/people/?keywords=founder",
    ):
        with pytest.raises(ValueError):
            parse_search_response(response(request, url=url), request, observed_at=NOW)


def test_malformed_and_external_links_rejected_and_error_payload_not_exposed():
    request = LinkedInSearch(operation="search_people", keywords="founder")
    payload = response(request, section_errors={"search_results": {"secret": "session-secret"}})
    payload["references"]["search_results"].extend(
        [
            {"kind": "person", "url": "https://evil.example/in/fake"},
            {"kind": "company", "url": "https://www.linkedin.com/in/other/"},
        ]
    )
    page = parse_search_response(payload, request, observed_at=NOW)
    assert page.rejected_count == 2 and page.status == "partial_not_live_verified"
    assert page.failed_sections == ("search_results",)
    assert "session-secret" not in page.model_dump_json()


def test_empty_section_never_claims_successful_zero_results():
    request = LinkedInSearch(operation="search_posts", keywords="hiring")
    with pytest.raises(ValueError, match="readable"):
        parse_search_response(
            response(request, sections={"search_results": ""}), request, observed_at=NOW
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {"operation": "search_people", "keywords": "founder", "current_company": "Acme"},
        {"operation": "search_people", "keywords": "founder", "network": ["everyone"]},
        {"operation": "search_people", "keywords": "founder", "date_posted": "past_week"},
        {"operation": "search_posts", "keywords": "hiring", "location": "London"},
        {"operation": "send_message", "keywords": "hello"},
    ],
)
def test_unsupported_filters_and_write_operations_never_get_tool_arguments(arguments):
    with pytest.raises(ValidationError):
        LinkedInSearch(**arguments)
