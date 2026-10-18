"""Typed owner-bound execution seam for the prepared isolated social worker."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from skriller.connections.execution import run_connected
from skriller.connectors.facebook_read import (
    FacebookProfile,
    FacebookRead,
    FacebookSearch,
    FacebookSearchPage,
)
from skriller.connectors.instagram_read import (
    InstagramProfile,
    InstagramRead,
    InstagramReference,
    InstagramSearch,
)
from skriller.connectors.social_worker import OPERATIONS
from skriller.security.runner import IsolatedRunner


class SocialUnavailable(ValueError):
    retry_after_seconds = None

    def __init__(self, code="source_unavailable"):
        self.code = (
            code
            if code
            in {
                "source_unavailable",
                "auth_expired",
                "access_denied",
                "rate_limited",
                "needs_connection",
            }
            else "source_unavailable"
        )
        super().__init__("Connected social operation did not complete")


@dataclass(frozen=True)
class SocialReceipt:
    data: InstagramProfile | list[InstagramReference] | FacebookProfile | FacebookSearchPage
    api_requests: int
    network_requests_seen: int


class ConcreteSocialExecutor:
    def __init__(
        self,
        source: Literal["instagram", "facebook"],
        image: str,
        *,
        docker: Path = Path("/usr/local/bin/docker"),
    ):
        if source not in {"instagram", "facebook"}:
            raise ValueError("A named social source is required")
        self.source = source
        self.runner = IsolatedRunner(image, docker=docker)

    def execute(
        self, request, *, database, store, context, timeout=40, expected_credential_ref=None
    ):
        operation = self.source + (
            "_profile" if isinstance(request, (InstagramRead, FacebookRead)) else "_search"
        )
        if not isinstance(request, OPERATIONS[operation]) or not 0 < timeout <= 45:
            raise ValueError("A source-aligned bounded read request is required")
        result = run_connected(
            database,
            store,
            context,
            self.runner,
            operation,
            request.model_dump_json(),
            timeout=timeout,
            max_output=1_048_576,
            expected_credential_ref=expected_credential_ref,
        )
        if result.status != "completed":
            raise SocialUnavailable(
                "needs_connection" if result.status == "needs_connection" else "source_unavailable"
            )
        try:
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise TypeError("Invalid worker envelope")
            if "_skriller_error" in payload:
                raise SocialUnavailable(payload["_skriller_error"])
            if set(payload) != {"data", "network_requests_seen", "api_requests"}:
                raise ValueError("Invalid worker envelope")
            network, api = payload["network_requests_seen"], payload["api_requests"]
            if (
                type(network) is not int
                or type(api) is not int
                or not 0 <= api <= network <= 80
                or api
                > (
                    3
                    if operation == "instagram_profile"
                    else 1
                    if operation == "instagram_search"
                    else 0
                )
            ):
                raise ValueError("Invalid worker request counts")
            if self.source == "instagram" and api < 1:
                raise ValueError("Instagram output requires an actual API read")
            raw = json.dumps(payload["data"], allow_nan=False)
            data: InstagramProfile | list[InstagramReference] | FacebookProfile | FacebookSearchPage
            if operation == "instagram_profile":
                assert isinstance(request, InstagramRead)
                data = InstagramProfile.model_validate_json(raw)
                if data.username != request.username:
                    raise ValueError("Profile does not match its request")
            elif operation == "facebook_profile":
                assert isinstance(request, FacebookRead)
                data = FacebookProfile.model_validate_json(raw)
                if data.username != request.username:
                    raise ValueError("Profile does not match its request")
            elif operation == "instagram_search":
                assert isinstance(request, InstagramSearch)
                data = TypeAdapter(list[InstagramReference]).validate_json(raw)
                if len(data) > request.limit:
                    raise ValueError("Search output exceeds its bound")
            else:
                assert isinstance(request, FacebookSearch)
                data = FacebookSearchPage.model_validate_json(raw)
                if len(data.references) + data.omitted_unsupported > request.limit:
                    raise ValueError("Search output exceeds its bound")
            return SocialReceipt(data, api, network)
        except SocialUnavailable:
            raise
        except (ValueError, TypeError, KeyError):
            raise SocialUnavailable() from None

    def search_page(self, query, *, limit, database, store, context):
        from skriller.connections.store import ConnectionUnavailable
        from skriller.connectors.search import SearchHit, SearchPage

        request = (
            InstagramSearch(query=query, limit=limit)
            if self.source == "instagram"
            else FacebookSearch(query=query, limit=limit)
        )
        try:
            with database.tenant(context.actor_id, str(context.workspace_id)) as session:
                material = store.load_for_runner(session, context, self.source + "_search")
        except ConnectionUnavailable:
            raise SocialUnavailable("needs_connection") from None
        receipt = self.execute(
            request,
            database=database,
            store=store,
            context=context,
            expected_credential_ref=material.credential_ref,
        )
        data = receipt.data
        hits = []
        if self.source == "instagram":
            if not isinstance(data, list):
                raise SocialUnavailable()
            for index, reference in enumerate(data, 1):
                hits.append(
                    SearchHit(
                        title=(reference.name or reference.username)[:300],
                        snippet=reference.name[:300],
                        url=reference.source_url,
                        provider="opencli_instagram",
                        evidence_kind="search_reference",
                        rank=index,
                    )
                )
            omitted = 0
        else:
            if not isinstance(data, FacebookSearchPage):
                raise SocialUnavailable()
            for index, reference in enumerate(data.references, 1):
                hits.append(
                    SearchHit(
                        title=reference.title,
                        snippet=reference.excerpt,
                        url=reference.source_url,
                        provider="opencli_facebook",
                        evidence_kind="search_reference",
                        rank=index,
                    )
                )
            omitted = data.omitted_unsupported
        return SearchPage(
            hits=hits,
            rejected=omitted,
            truncated=len(hits) >= limit,
            query=query,
            read_connection_ref=material.connection_ref,
            read_credential_ref=material.credential_ref,
        )


def social_binding(source, reader=None, *, database=None, store=None, operation="discover"):
    from datetime import UTC, datetime

    from skriller.connectors.registry import AdapterBinding
    from skriller.contracts import Capability

    if source not in {"instagram", "facebook"} or operation not in {"discover", "read"}:
        raise ValueError("A named social read/search is required")

    def execute(context, serialized_request):
        if reader is None or reader.source != source or database is None or store is None:
            raise SocialUnavailable()
        schema = (
            (InstagramRead if source == "instagram" else FacebookRead)
            if operation == "read"
            else (InstagramSearch if source == "instagram" else FacebookSearch)
        )
        request = schema.model_validate_json(serialized_request)
        remaining = (context.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise SocialUnavailable()
        return reader.execute(
            request, database=database, store=store, context=context, timeout=min(40, remaining)
        )

    return AdapterBinding(
        Capability(
            source=source,
            operation=operation,
            engineering_status="implemented",
            operational_status="experimental" if reader else "unavailable",
            auth_kind="session",
            access_route=(
                "Owner-connected named profile header; Instagram explicitly public, Facebook visibility/identity unknown; no group content or owner analytics"
                if operation == "read"
                else "Owner-connected copied search references; Instagram public-only, Facebook visibility/identity unknown; group routes omitted, no profile read or analytics"
            ),
            version="opencli_" + source + "_" + operation + "_v1",
            allowed_fields=[
                "source_url",
                "profile_header" if operation == "read" else "search_reference",
            ],
        ),
        "opencli_" + source + "_" + operation + "_v1",
        execute,
    )
