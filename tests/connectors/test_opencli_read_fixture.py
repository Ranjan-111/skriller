"""Execute the pinned read subset without a source account or browser bridge."""

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from skriller.connectors.instagram_read import (
    InstagramRead,
    InstagramSearch,
    parse_profile_response,
    parse_search_response,
)

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module", params=[False, True], ids=["upstream", "adapted"])
def copied_read_report(request):
    node = shutil.which("node")
    if node is None or not (ROOT / "apps/web/node_modules/jsdom").exists():
        pytest.fail("Installed Node and web fixture dependencies are required")
    arguments = [node, "--experimental-vm-modules", "scripts/probes/opencli_read_fixture.mjs"]
    if request.param:
        arguments.append("--adapted")
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["mode"] == "offline_synthetic_fixture"
    assert report["source_calls"] == 0
    assert report["platform_enabled"] is False
    assert report["adapted"] is request.param
    assert len(report["cases"]) == (13 if request.param else 10)
    if os.environ.get("SKRILLER_WRITE_SOCIAL_REPORTS") == "1":
        report.update(
            recorded_at=datetime.now(UTC).isoformat(),
            source_commit="e6174a952c763a836a9bb0dd2f097d2962b3876b",
            release_gate_passed=False,
            scope="Synthetic page/fetch responses only; requests are mocked, no platform or production isolation proof",
            implementation_sha256={
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in [
                    "scripts/probes/opencli_read_fixture.mjs",
                    "src/skriller/_vendor/opencli/PROVENANCE.json",
                    "src/skriller/connectors/instagram_read.py",
                    "src/skriller/connectors/facebook_read.py",
                    "src/skriller/connectors/social_read.py",
                    "src/skriller/connectors/social_worker.py",
                    "scripts/opencli_read_modules.mjs",
                    "scripts/build_social_read_scripts.mjs",
                ]
            },
        )
        mode = "ADAPTED" if request.param else "UPSTREAM"
        (ROOT / f"docs/completions/SOCIAL-READ-{mode}-LOCAL.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
    return {"adapted": request.param, "cases": {row["id"]: row for row in report["cases"]}}


@pytest.mark.parametrize(
    "case,requests",
    [
        ("instagram-search-public-private", 1),
        ("instagram-profile-missing-counts", 1),
        ("instagram-profile-business-fallback", 3),
        ("instagram-profile-rate-limit", 1),
        ("instagram-profile-login", 1),
        ("instagram-profile-challenge", 1),
        ("instagram-profile-malformed", 1),
        ("facebook-search-identity-and-decoys", 0),
        ("facebook-search-login", 0),
        ("facebook-profile-scoped-header-and-display-count", 0),
    ],
)
def test_copied_read_contract_on_offline_fixture(copied_read_report, case, requests):
    row = copied_read_report["cases"][case]
    assert row["outcome"] == "passed"
    assert row["requests"] == requests


@pytest.mark.parametrize("case", ["private", "unknown", "mismatched"])
def test_adaptation_rejects_nonpublic_or_wrong_profile(copied_read_report, case):
    key = "instagram-profile-rejects-" + case
    if not copied_read_report["adapted"]:
        assert key not in copied_read_report["cases"]
        return
    row = copied_read_report["cases"][key]
    assert row["outcome"] == "passed"
    assert row["no_retry"] is True
    assert row["requests"] == 1


@pytest.mark.parametrize(
    "case", ["search-public-private", "profile-missing-counts", "profile-business-fallback"]
)
def test_executed_module_output_passes_only_the_public_adapted_contract(copied_read_report, case):
    sample = copied_read_report["cases"]["instagram-" + case]["sample"]
    observed = datetime(2026, 10, 17, tzinfo=UTC)

    def parse():
        if case.startswith("search"):
            return parse_search_response(
                sample, InstagramSearch(query="synthetic", limit=3), observed_at=observed
            )
        return parse_profile_response(
            sample, InstagramRead(username="synthetic"), observed_at=observed
        )

    if not copied_read_report["adapted"]:
        with pytest.raises(ValueError):
            parse()
        return
    parsed = parse()
    if case.startswith("search"):
        assert len(parsed) == 1
        assert parsed[0].username == "public_fixture"
    elif case == "profile-missing-counts":
        assert parsed.followers is None and parsed.posts is None
    else:
        assert parsed.followers == 12


@pytest.mark.parametrize(
    "case", ["search-identity-and-decoys", "profile-scoped-header-and-display-count"]
)
def test_executed_facebook_modules_preserve_distinct_content_and_display_counts(
    copied_read_report, case
):
    from skriller.connectors.facebook_read import FacebookRead, FacebookSearch
    from skriller.connectors.facebook_read import parse_profile_response as profile
    from skriller.connectors.facebook_read import parse_search_response as search

    sample = copied_read_report["cases"]["facebook-" + case]["sample"]
    observed = datetime(2026, 10, 17, tzinfo=UTC)
    if case.startswith("search"):
        parsed = search(sample, FacebookSearch(query="synthetic"), observed_at=observed)
        assert len(parsed.references) == 2
        assert len({row.source_url for row in parsed.references}) == 2
        assert all(row.company_identity == "unknown" for row in parsed.references)
    else:
        parsed = profile(sample, FacebookRead(username="synthetic"), observed_at=observed)
        assert parsed.followers_display == "1.2K followers"
        assert parsed.friends_display is None
