from datetime import UTC, datetime

import pytest

from skriller.connectors.linkedin_read import LinkedInRead, parse_read_response, request_for_url
from skriller.security.runner import reviewed_command


@pytest.mark.parametrize(
    "operation,identifier",
    [("read_profile", "synthetic"), ("read_company", "synthetic"), ("read_post", "12345")],
)
def test_typed_resources_reuse_worker_without_arbitrary_navigation(operation, identifier):
    request = LinkedInRead(operation=operation, resource_id=identifier)
    assert request_for_url(request.target_url()) == request
    command = reviewed_command("linkedin_resource_read", request.model_dump_json())
    assert command[:3] == ["python", "-m", "skriller.connectors.linkedin_worker"]
    result = parse_read_response(
        {
            "url": request.target_url(),
            "sections": {request.section(): "Synthetic Founder\nHead of Operations"},
        },
        request,
        observed_at=datetime.now(UTC),
    )
    assert result.text.endswith("Operations") and result.subject_identity == "unknown"
    assert result.contact_details == "unavailable" and not result.coverage_complete
    with pytest.raises(ValueError):
        reviewed_command("linkedin_search", request.model_dump_json())


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/in/me/",
        "https://www.linkedin.com/in/person/?token=x",
        "https://evil.example/in/person/",
        "https://www.linkedin.com/messaging/",
        "https://www.linkedin.com/in/person/details/contact-info/",
        "https://user@www.linkedin.com/in/person/",
        "https://www.linkedin.com:80/in/person/",
        "https://www.linkedin.com/in/person/#fragment",
    ],
)
def test_read_rejects_ambient_identity_contacts_and_unreviewed_routes(url):
    with pytest.raises(ValueError):
        request_for_url(url)


@pytest.mark.parametrize("change", ["redirect", "challenge", "error", "missing", "extra"])
def test_blocked_or_unaligned_sections_never_become_resource_evidence(change):
    request = LinkedInRead(operation="read_profile", resource_id="synthetic")
    payload = {"url": request.target_url(), "sections": {"main_profile": "Synthetic profile"}}
    if change == "redirect":
        payload["url"] = "https://www.linkedin.com/checkpoint/challenge/"
    elif change == "challenge":
        payload["sections"]["main_profile"] = "Sign in to LinkedIn"
    elif change == "error":
        payload["section_errors"] = {"main_profile": "Private source error"}
    elif change == "missing":
        payload["sections"]["main_profile"] = ""
    else:
        payload["sections"]["contact_info"] = "private"
    with pytest.raises(ValueError):
        parse_read_response(payload, request, observed_at=datetime.now(UTC))


def test_api_refuses_a_resource_attached_to_another_candidate():
    from uuid import uuid4

    from skriller.research.router import ResearchCandidate

    request = LinkedInRead(operation="read_profile", resource_id="synthetic")
    resource = parse_read_response(
        {"url": request.target_url(), "sections": {"main_profile": "Synthetic Founder"}},
        request,
        observed_at=datetime.now(UTC),
    )
    data = {
        "id": uuid4(),
        "title": "Synthetic",
        "url": request.target_url(),
        "snippet": "reference",
        "source": "linkedin",
        "provider": "linkedin_mcp",
        "evidence_kind": "search_reference",
        "qualification": "unverified",
        "observed_at": datetime.now(UTC),
        "provenance": [],
        "linkedin_read": {"evidence_id": uuid4(), "resource": resource},
    }
    assert ResearchCandidate.model_validate(data).linkedin_read.resource.resource_kind == "profile"
    data["url"] = "https://www.linkedin.com/in/other/"
    with pytest.raises(ValueError):
        ResearchCandidate.model_validate(data)
