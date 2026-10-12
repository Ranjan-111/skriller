import importlib.util
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

PATH = Path(__file__).parents[1] / "fixtures/harness.py"
spec = importlib.util.spec_from_file_location("skriller_fixture_harness", PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_provider_replay_and_frozen_deadlines():
    clock = module.FrozenClock()
    before = clock.now()
    clock.advance(30)
    assert (clock.now() - before).total_seconds() == 30
    with pytest.raises(ValueError):
        clock.advance(-1)
    search = module.ReplayProvider({"fintech": [{"url": "https://aurora.example/about"}]})
    model = module.ReplayProvider({"company": {"name": "Aurora Ledger", "email": None}})
    assert search.run("fintech")[0]["url"].endswith("/about")
    assert model.run("company")["email"] is None
    with pytest.raises(AssertionError, match="Unlabelled"):
        search.run("unplanned paid call")


@pytest.mark.local_server
def test_real_loopback_fixture_and_failure_response():
    body = (PATH.parent / "research/discussion.html").read_bytes()
    with module.FixtureServer({"/post": (200, body), "/limited": (429, b"slow down")}) as server:
        with urlopen(server.url + "/post", timeout=2) as response:
            assert b"six hours" in response.read()
        with pytest.raises(HTTPError) as error:
            urlopen(server.url + "/limited", timeout=2)
        assert error.value.code == 429
        with pytest.raises(HTTPError) as missing:
            urlopen(server.url + "/unknown", timeout=2)
        assert missing.value.code == 404


def test_missing_or_duplicate_expected_labels_fail_validation():
    import copy
    import json

    corpus = json.loads((PATH.parent / "research/labels.json").read_text())
    module.validate_labels(corpus)
    broken = copy.deepcopy(corpus)
    broken["expected"]["confirmed"] = []
    with pytest.raises(ValueError, match="exactly one"):
        module.validate_labels(broken)
    broken = copy.deepcopy(corpus)
    del broken["companies"][0]["url"]
    with pytest.raises(ValueError, match="evidence labels"):
        module.validate_labels(broken)
    people = json.loads((PATH.parent / "research/people.json").read_text())
    assert people[0]["name"] == people[1]["name"]
    assert people[0]["id"] != people[1]["id"]
    assert people[0]["company_id"] != people[1]["company_id"]
