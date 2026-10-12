import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("reddit_probe", ROOT / "scripts/probes/reddit.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_bridge_and_configuration_do_not_prove_reddit_session():
    def forbidden():
        pytest.fail("configuration check loaded platform backend")

    result = module.probe(configured=True, bridge_available=True, backend_loader=forbidden)
    assert result["status"] == "unvalidated"
    assert result["validated"] is False


def test_no_anonymous_or_browser_cookie_fallback():
    def forbidden():
        pytest.fail("probe attempted fallback auth")

    result = module.probe(live=True, backend_loader=forbidden)
    assert result["validated"] is False
    assert "cookie file required" in result["reason"]


@pytest.fixture
def cookie_file(tmp_path):
    path = tmp_path / "explicit.json"
    path.write_text(json.dumps({"cookies": {"reddit_session": "explicit-test-session"}}))
    path.chmod(0o600)
    return path


def test_fixture_search_reuses_acquired_client_parser_and_reports_pagination(cookie_file):
    Credential, _Client, parse_listing, parse_detail = module.backend()
    observed = []
    fixture = json.loads((module.SOURCE / "tests/fixtures/listing.json").read_text())

    class Client:
        def __init__(self, credential, **kwargs):
            observed.append((credential.cookies, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def search(self, **kwargs):
            assert kwargs == {"query": "fintech", "limit": 5}
            return fixture

    result = module.probe(
        live=True,
        cookie_file=cookie_file,
        backend_loader=lambda: (Credential, Client, parse_listing, parse_detail),
    )
    assert observed == [
        (
            {"reddit_session": "explicit-test-session"},
            {"timeout": 15, "request_delay": 1, "max_retries": 0},
        )
    ]
    assert result["status"] == "verified"
    assert result["count"] == len(fixture["data"]["children"])
    assert result["pagination_cursor_present"] == bool(fixture["data"]["after"])
    assert "title" in result["fields"]
    assert "explicit-test-session" not in json.dumps(result)


def test_errors_do_not_leak_cookie_values(cookie_file):
    def fail():
        raise RuntimeError("secret explicit-test-session")

    result = module.probe(live=True, cookie_file=cookie_file, backend_loader=fail)
    assert result["status"] == "failed"
    assert "secret" not in result["reason"]
    assert "explicit-test-session" not in result["reason"]


def test_fixture_thread_reads_actual_acquired_post_parser(cookie_file):
    Credential, _Client, parse_listing, parse_detail = module.backend()
    fixture = json.loads((module.SOURCE / "tests/fixtures/post_detail.json").read_text())

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_post_comments(self, **kwargs):
            assert kwargs == {"post_id": "abc123", "limit": 5}
            return fixture

    result = module.probe(
        live=True,
        cookie_file=cookie_file,
        operation="read",
        post_id="abc123",
        backend_loader=lambda: (Credential, Client, parse_listing, parse_detail),
    )
    assert result["status"] == "verified"
    assert result["count"] == 1
    assert result["comments_returned"] == len(parse_detail(fixture).comments)


def test_insecure_or_symlink_cookie_file_is_rejected(cookie_file, tmp_path):
    cookie_file.chmod(0o644)
    assert module.probe(live=True, cookie_file=cookie_file)["status"] == "failed"
    cookie_file.chmod(0o600)
    link = tmp_path / "symlink.json"
    link.symlink_to(cookie_file)
    assert module.probe(live=True, cookie_file=link)["status"] == "failed"


def test_writes_and_invalid_thread_ids_are_rejected():
    with pytest.raises(ValueError, match="search/read"):
        module.probe(operation="post_comment")
    with pytest.raises(ValueError, match="post ID"):
        module.probe(operation="read", post_id="../../etc/passwd")


def test_source_pin_and_license_packaging_gap_are_reported():
    source = module.verify_source()
    assert source["commit"] == "5e4fb3720d5c174e976cd425ccc3b879d52cac66"
    assert source["license"] == "Apache-2.0"
    assert source["license_files"] == []


@pytest.mark.live
def test_controlled_live_reddit_search_operation():
    import os

    cookie_file = os.environ.get("SKRILLER_REDDIT_PROBE_COOKIE_FILE")
    if not cookie_file:
        pytest.skip("Requires explicit isolated Reddit cookie file")
    report = module.probe(live=True, cookie_file=Path(cookie_file), query="fintech")
    assert report["status"] == "verified", report
