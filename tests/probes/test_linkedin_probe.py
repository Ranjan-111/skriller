import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("linkedin_probe", ROOT / "scripts/probes/linkedin.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.asyncio
async def test_mcporter_configuration_does_not_validate_operations():
    async def forbidden(*args):
        pytest.fail("offline configuration probe attempted a tool call")

    result = await module.probe(configured=True, caller=forbidden)
    assert result["status"] == "unvalidated"
    assert result["validated"] is False


@pytest.mark.asyncio
async def test_live_without_explicit_existing_session_does_not_call_backend():
    async def forbidden(*args):
        pytest.fail("probe attempted implicit authentication")

    result = await module.probe(live=True, endpoint="http://127.0.0.1:8000/mcp", caller=forbidden)
    assert result["validated"] is False
    assert "existing session" in result["reason"]


@pytest.mark.asyncio
async def test_fixture_search_measures_content_fields_and_bounds_pagination():
    observed = []

    async def call(endpoint, operation, arguments):
        observed.append((operation, arguments))
        return {
            "url": "https://www.linkedin.com/search/results/content/?keywords=fintech&origin=FACETED_SEARCH",
            "sections": {"search_results": "Example founder hiring engineers"},
            "references": {
                "search_results": [
                    {
                        "kind": "feed_post",
                        "url": "https://www.linkedin.com/feed/update/urn:li:activity:12345/",
                    }
                ]
            },
        }

    result = await module.probe(
        live=True,
        endpoint="http://127.0.0.1:8000/mcp",
        session_confirmed=True,
        auto_import_disabled=True,
        operation="search_posts",
        arguments={"keywords": "fintech", "max_pages": 10},
        caller=call,
    )
    assert observed == [
        ("search_posts", {"keywords": "fintech", "date_posted": None, "max_pages": 1})
    ]
    assert result["status"] == "verified"
    assert result["sections"] == ["search_results"]
    assert result["reference_count"] == 1


@pytest.mark.asyncio
async def test_partial_and_empty_content_cannot_be_successful_coverage():
    async def partial(*args):
        return {
            "sections": {"profile": "Example"},
            "section_errors": {"contact_info": {"error_type": "unavailable"}},
        }

    async def empty(*args):
        return {"sections": {"profile": ""}}

    args = {
        "live": True,
        "endpoint": "http://127.0.0.1:8000/mcp",
        "session_confirmed": True,
        "auto_import_disabled": True,
        "operation": "get_person_profile",
    }
    result = await module.probe(**args, caller=partial)
    assert result["status"] == "partial"
    assert result["validated"] is False
    assert (await module.probe(**args, caller=empty))["status"] == "failed"


@pytest.mark.asyncio
async def test_backend_that_drops_requested_search_filter_cannot_be_ready():
    async def ignored_filter(*args):
        return {
            "url": "https://www.linkedin.com/search/results/people/?keywords=founder",
            "sections": {"search_results": "A founder reference"},
        }

    result = await module.probe(
        live=True,
        endpoint="http://127.0.0.1:8000/mcp",
        session_confirmed=True,
        auto_import_disabled=True,
        operation="search_people",
        arguments={"keywords": "founder", "location": "London"},
        caller=ignored_filter,
    )
    assert result["status"] == "failed" and result["validated"] is False


@pytest.mark.asyncio
async def test_errors_do_not_expose_url_credentials():
    async def fail(*args):
        raise RuntimeError("http://user:password@proxy.test/?token=secret")

    result = await module.probe(
        live=True,
        endpoint="http://127.0.0.1:8000/mcp",
        session_confirmed=True,
        auto_import_disabled=True,
        caller=fail,
    )
    assert result["status"] == "failed"
    assert "password" not in result["reason"]
    assert "secret" not in result["reason"]


@pytest.mark.asyncio
async def test_non_loopback_and_write_operations_are_rejected():
    with pytest.raises(ValueError, match="read operations"):
        await module.probe(operation="send_message")
    with pytest.raises(ValueError, match="loopback"):
        await module.probe(
            live=True,
            endpoint="http://external.example/mcp",
            session_confirmed=True,
            auto_import_disabled=True,
        )


def test_source_pin_and_license_are_real_acquired_files():
    source = module.verify_source()
    assert source["commit"] == "f1ba6aa87234526cf22812e59233e0c619073529"
    assert source["license_files"] == ["LICENSE", "NOTICE"]


@pytest.mark.live
@pytest.mark.asyncio
async def test_controlled_live_linkedin_operation():
    import os

    endpoint = os.environ.get("SKRILLER_LINKEDIN_PROBE_ENDPOINT")
    if (
        not endpoint
        or os.environ.get("SKRILLER_LINKEDIN_SESSION_CONFIRMED") != "1"
        or os.environ.get("SKRILLER_LINKEDIN_AUTO_IMPORT_DISABLED") != "1"
    ):
        pytest.skip("Requires explicit loopback server, existing session and disabled auto-import")
    report = await module.probe(
        live=True,
        endpoint=endpoint,
        session_confirmed=True,
        auto_import_disabled=True,
        arguments={"keywords": "fintech founder"},
    )
    assert report["status"] == "verified", report
