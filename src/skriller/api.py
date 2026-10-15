"""HTTP boundary. Long research work executes outside request processes."""

import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from kombu import Connection, Queue
from sqlalchemy import create_engine, text

from skriller.auth import Identity, require_identity
from skriller.connections.router import router as connections_router
from skriller.connectors.router import router as connectors_router
from skriller.connectors.search import ExaKeylessSearch
from skriller.contracts import Capability, ExecutionContext, Failure, ProgressEvent, SearchPlan
from skriller.db import Database
from skriller.entitlements_router import router as entitlements_router
from skriller.erasure_router import router as erasure_router
from skriller.exports.router import router as exports_router
from skriller.lists_router import router as lists_router
from skriller.progress import router as progress_router
from skriller.qualification.router import router as identity_router
from skriller.research.router import router as research_router
from skriller.research.template_router import router as template_router
from skriller.settings import Settings
from skriller.storage.configuration import configured_storage


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


def worker_available(url: str) -> bool:
    """Read the durable queue's consumer count without publishing or using control queues."""
    try:
        with Connection(
            url, connect_timeout=2, transport_options={"read_timeout": 2}
        ) as connection:
            connection.connect()
            channel = connection.channel()
            try:
                status = Queue("skriller.jobs", channel=channel).queue_declare(passive=True)
                return status.consumer_count > 0
            finally:
                channel.close()
    except Exception:  # noqa: BLE001 - health must redact broker credentials/errors
        return False


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings or Settings()

    @asynccontextmanager
    async def lifespan(application):
        application.state.evidence_storage = configured_storage(configuration)
        try:
            yield
        finally:
            try:
                await asyncio.to_thread(application.state.evidence_storage.close)
            finally:
                await asyncio.to_thread(application.state.database.dispose)

    app = FastAPI(title="Skriller", version="0.1.0", lifespan=lifespan)
    app.state.settings = configuration
    app.state.search_provider = (
        ExaKeylessSearch() if configuration.search_provider == "exa_keyless" else None
    )
    app.state.database = Database(configuration.application_database_url)
    app.include_router(progress_router)
    app.include_router(research_router)
    app.include_router(template_router)
    app.include_router(connections_router)
    app.include_router(connectors_router)
    app.include_router(exports_router)
    app.include_router(lists_router)
    app.include_router(entitlements_router)
    app.include_router(erasure_router)
    app.include_router(identity_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configuration.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
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
        db, broker, worker = await asyncio.gather(
            asyncio.to_thread(database_available, configuration.database_url),
            asyncio.to_thread(broker_available, configuration.broker_url),
            asyncio.to_thread(worker_available, configuration.broker_url),
        )
        return JSONResponse(
            {
                "status": "ready" if db and broker and worker else "unavailable",
                "dependencies": {"database": db, "broker": broker, "worker": worker},
            },
            status_code=200 if db and broker and worker else 503,
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
