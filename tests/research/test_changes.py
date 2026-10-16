from copy import deepcopy

from skriller.research.changes import meaningful_changes


def member(role, *, observed_at="2026-01-01T00:00:00+00:00"):
    return {
        "entity_id": "entity-1",
        "display_name": "Example Person",
        "identity_status": "reviewed_facts",
        "values": [
            {
                "field": "current_role",
                "value": role,
                "evidence": [
                    {
                        "source_url": "https://example.org/profile",
                        "source_platform": "web",
                        "collected_at": observed_at,
                        "excerpt": f"Current role: {role}",
                    }
                ],
            }
        ],
    }


def payload(item, timestamp):
    return {"snapshot_at": timestamp, "members": [item]}


def test_refresh_timestamp_and_observation_time_alone_are_not_meaningful():
    before = member("Engineer")
    after = member("Engineer", observed_at="2026-10-16T00:00:00+00:00")
    assert meaningful_changes(payload(before, "before"), payload(after, "after")) == []


def test_changed_role_returns_new_verbatim_citation_and_unverified_qualification():
    before = member("Engineer")
    after = member("Director")
    result = meaningful_changes(payload(before, "before"), payload(after, "after"))
    assert len(result) == 1
    assert result[0]["previous_value"] == "Engineer"
    assert result[0]["current_value"] == "Director"
    assert result[0]["qualification"] == "accepted_observation_not_independently_verified"
    assert result[0]["citations"][0]["quote"] == "Current role: Director"
    assert len(result[0]["citations"][0]["excerpt_sha256"]) == 64


def test_ambiguous_or_suppression_unresolved_role_does_not_become_a_report():
    before = member("Engineer")
    after = member("Director")
    after["identity_status"] = "suppression_unresolved"
    assert meaningful_changes(payload(before, "a"), payload(after, "b")) == []
    after = deepcopy(member("Director"))
    after["values"].append(deepcopy(after["values"][0]))
    assert meaningful_changes(payload(before, "a"), payload(after, "b")) == []
