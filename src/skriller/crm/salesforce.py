"""Salesforce Lead upsert preparation using the existing copied export path.

No network or credentials are used here. The external-ID and metadata custom
fields must be provisioned in the destination org before delivery is enabled.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from uuid import UUID

import httpx

from skriller.db.repositories import require_owner, scope
from skriller.exports import create_export, download_export

TARGETS = {"FirstName", "LastName", "Company", "Title", "Website", "City", "Country", "Email"}
EMAIL_FIELDS = {"work_email", "professional_email"}


@dataclass(frozen=True)
class LeadUpsert:
    external_id: str
    fields: dict[str, str]


class SalesforceUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Salesforce delivery unavailable")


class SalesforceAuthorizationExpired(SalesforceUnavailable):
    pass


def validate_instance(value: str):
    if not re.fullmatch(
        r"https://[a-zA-Z0-9][a-zA-Z0-9-]{0,100}\.(?:sandbox\.|develop\.)?my\.salesforce\.com",
        value,
    ):
        raise SalesforceUnavailable()
    return value


def upsert_lead(
    instance_url: str,
    access_token: str,
    lead: LeadUpsert,
    *,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Single bounded PATCH, no redirects/retries, unique external ID required.

    Only an org-specific Salesforce origin is supported. Credential resolution,
    fresh qualification and privacy locking belong to the trusted dispatcher;
    this low-level adapter is not exposed to API/MCP callers.
    """
    instance_url = validate_instance(instance_url)
    if (
        not 16 <= len(access_token) <= 8192
        or any(ord(char) < 33 or ord(char) > 126 for char in access_token)
        or not re.fullmatch(r"[0-9a-f]{64}", lead.external_id)
        or not {"LastName", "Company", "Skriller_Fit__c"} <= lead.fields.keys()
        or not set(lead.fields) <= TARGETS | {"Skriller_Fit__c"}
        or lead.fields["Skriller_Fit__c"] not in {"confirmed", "near_match"}
    ):
        raise SalesforceUnavailable()
    url = (
        instance_url
        + "/services/data/v66.0/sobjects/Lead/Skriller_Entity_ID__c/"
        + lead.external_id
    )
    deadline = time.monotonic() + 10
    try:
        with (
            httpx.Client(
                timeout=httpx.Timeout(5, connect=3),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client,
            client.stream(
                "PATCH",
                url,
                headers={"Authorization": "Bearer " + access_token},
                json=lead.fields,
            ) as response,
        ):
            if response.status_code == 401:
                raise SalesforceAuthorizationExpired()
            if response.status_code not in {201, 204}:
                raise SalesforceUnavailable()
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 65536 or time.monotonic() > deadline:
                    raise SalesforceUnavailable()
            return "created" if response.status_code == 201 else "updated"
    except (httpx.HTTPError, ValueError):
        raise SalesforceUnavailable() from None


def map_lead(workspace_id: str, row: dict, field_map: dict[str, str]) -> LeadUpsert:
    workspace_id = str(UUID(workspace_id))
    entity_id = str(UUID(row["entity_id"]))
    if (
        not field_map
        or len(field_map) > len(TARGETS)
        or len(set(field_map.values())) != len(field_map)
        or not {"LastName", "Company"} <= set(field_map.values())
        or row.get("fit") not in {"confirmed", "near_match"}
    ):
        raise ValueError("Explicit Salesforce Lead field map required")
    values = {}
    for source, target in field_map.items():
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", source)
            or target not in TARGETS
            or (target == "Email" and source not in EMAIL_FIELDS)
            or (source in EMAIL_FIELDS and target != "Email")
            or "phone" in source
            or ("email" in source and source not in EMAIL_FIELDS)
        ):
            raise ValueError("Unsupported Salesforce field mapping")
        value = row.get("field." + source)
        # Unknown/conflicting values stay absent; never overwrite remote data with null.
        if value is None:
            continue
        limits = {
            "LastName": 80,
            "FirstName": 40,
            "Company": 255,
            "Title": 128,
            "Website": 255,
            "City": 40,
            "Country": 80,
            "Email": 80,
        }
        if not isinstance(value, str) or not value.strip() or len(value) > limits[target]:
            raise ValueError("Salesforce field exceeds destination bounds")
        values[target] = value
    if not {"LastName", "Company"} <= values.keys():
        raise ValueError("Evidence-backed last name and company required")
    # No Lead Status/contact-status mapping: near matches retain their literal fit.
    values["Skriller_Fit__c"] = row["fit"]
    external_id = hashlib.sha256((workspace_id + ":" + entity_id).encode()).hexdigest()
    return LeadUpsert(external_id, values)


def prepare_leads(
    session,
    storage,
    plan_id: str,
    entity_ids: tuple[str, ...],
    *,
    field_map: dict[str, str],
    selected_near_ids: tuple[str, ...] = (),
    opt_in: bool = False,
) -> list[LeadUpsert]:
    """Rebuild trusted rows at execution time; never trust queued raw field values.

    The caller's transaction holds the existing privacy lock through preparation.
    A future bounded dispatcher must keep that lock through each send and must
    resolve an owner-authorized encrypted destination connection itself.
    """
    require_owner(session)
    if opt_in is not True:
        raise ValueError("Explicit CRM export opt-in required")
    artifact = create_export(
        session,
        storage,
        plan_id,
        entity_ids,
        format="json",
        selected_near_ids=selected_near_ids,
    )
    content, _ = download_export(session, storage, artifact["id"])
    rows = json.loads(content)["records"]
    return [map_lead(scope(session), row, field_map) for row in rows]
