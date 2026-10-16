"""Deterministic, evidence-backed changes between immutable list snapshots."""

from hashlib import sha256


def meaningful_changes(previous: dict, current: dict) -> list[dict]:
    """Report supported current-role changes without treating refresh time as a change.

    Only reviewed members with one current-role value and source excerpts on both
    sides are comparable. Ambiguous, missing, or suppression-unresolved values
    fail closed. The report quotes the new source excerpt verbatim.
    """
    old_members = {
        item.get("entity_id"): item
        for item in previous.get("members", [])
        if item.get("identity_status") == "reviewed_facts"
    }
    reports = []
    for member in current.get("members", []):
        entity_id = member.get("entity_id")
        old = old_members.get(entity_id)
        if old is None or member.get("identity_status") != "reviewed_facts":
            continue
        old_roles = [v for v in old.get("values", []) if v.get("field") == "current_role"]
        new_roles = [v for v in member.get("values", []) if v.get("field") == "current_role"]
        if len(old_roles) != 1 or len(new_roles) != 1:
            continue
        before, after = old_roles[0], new_roles[0]
        if before.get("value") == after.get("value"):
            continue
        citations = [
            {
                "source_url": evidence["source_url"],
                "source_platform": evidence["source_platform"],
                "collected_at": evidence["collected_at"],
                "quote": evidence["excerpt"],
                "excerpt_sha256": sha256(evidence["excerpt"].encode()).hexdigest(),
            }
            for evidence in after.get("evidence", [])
            if isinstance(evidence.get("excerpt"), str)
            and evidence["excerpt"]
            and isinstance(evidence.get("source_url"), str)
        ]
        if not citations:
            continue
        reports.append(
            {
                "entity_id": entity_id,
                "display_name": member.get("display_name"),
                "field": "current_role",
                "previous_value": before.get("value"),
                "current_value": after.get("value"),
                "qualification": "accepted_observation_not_independently_verified",
                "citations": citations,
            }
        )
    return reports
