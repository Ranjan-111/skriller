"""HTTP boundary. Long research work executes outside request processes."""

import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from kombu import Connection
from sqlalchemy import create_engine, text

from skriller.auth import Identity, require_identity
from skriller.connectors.search import ExaKeylessSearch
from skriller.contracts import Capability, ExecutionContext, Failure, ProgressEvent, SearchPlan
from skriller.db import Database
from skriller.progress import router as progress_router
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend


def database_available(url: str) -> bool:
    engine = create_engine(url, connect_args={"connect_timeout": 2})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - health boundary must redact upstream failures
        return False
    finally:
        engine.dispose()


def broker_available(url: str) -> bool:
    try:
        with Connection(url, connect_timeout=2) as connection:
            connection.connect()
        return True
    except Exception:  # noqa: BLE001 - health boundary must redact upstream failures
        return False


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings or Settings()

    @asynccontextmanager
    async def lifespan(application):
        application.state.evidence_storage = EvidenceStorage(
            LocalBlobBackend(configuration.object_directory)
        )
        yield
        await asyncio.to_thread(application.state.database.dispose)

    app = FastAPI(title="Skriller", version="0.1.0", lifespan=lifespan)
    app.state.settings = configuration
    app.state.search_provider = (
        ExaKeylessSearch() if configuration.search_provider == "exa_keyless" else None
    )
    app.state.database = Database(configuration.application_database_url)
    app.include_router(progress_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configuration.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
    )

    @app.get("/health/live")
    async def live():
        return {"status": "ok", "service": "skriller-api"}

    @app.get("/v1/me")
    def current_user(identity: Annotated[Identity, Depends(require_identity)]):
        return {"uid": identity.uid, "email": identity.email}

    @app.get("/health/ready")
    async def ready():
        db, broker = await asyncio.gather(
            asyncio.to_thread(database_available, configuration.database_url),
            asyncio.to_thread(broker_available, configuration.broker_url),
        )
        return JSONResponse(
            {
                "status": "ready" if db and broker else "unavailable",
                "dependencies": {"database": db, "broker": broker},
            },
            status_code=200 if db and broker else 503,
        )

    def openapi():
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for model in (SearchPlan, Capability, ExecutionContext, Failure, ProgressEvent):
            definition = model.model_json_schema(ref_template="#/components/schemas/{model}")
            components.update(definition.pop("$defs", {}))
            components[model.__name__] = definition
        return schema

    app.openapi = openapi  # type: ignore[method-assign]  # FastAPI custom schema hook
    return app


app = create_app()
