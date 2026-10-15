"""Owner deletion with an explicit workspace-wide research/derivative effect."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from skriller.auth import Identity, require_identity
from skriller.contracts import Contract
from skriller.db import WorkspaceAccessDenied
from skriller.erasure import erase

router = APIRouter()


class ErasureResult(Contract):
    status: Literal["erased"]
    entity_ids: list[UUID]


@router.delete("/v1/workspaces/{workspace_id}/entities/{entity_id}", response_model=ErasureResult)
def delete(
    workspace_id: UUID,
    entity_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
    idempotency_key: Annotated[str, Header(min_length=1, max_length=100)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return erase(
                session,
                request.app.state.evidence_storage,
                str(entity_id),
                request_key=idempotency_key,
            )
    except WorkspaceAccessDenied:
        raise HTTPException(403, "Workspace owner permission required") from None
    except LookupError:
        raise HTTPException(404, "Entity unavailable") from None
    except ValueError:
        raise HTTPException(422, "Erasure request exceeds supported bounds") from None
