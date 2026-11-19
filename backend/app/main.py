"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import data, simulation, ws
from app.core.config import Settings, get_settings
from app.models.db import make_engine, make_session_factory
from app.repositories.sql import Repository
from app.services.runtime import SimulationRuntime

log = logging.getLogger("otst")


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Reject request bodies above ``max_bytes`` (checked on Content-Length and while streaming)."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    if int(v) > self.max_bytes:
                        await _send_json(send, 413, "payload_too_large", "Request body too large.")
                        return
                except ValueError:
                    await _send_json(send, 400, "bad_request", "Invalid Content-Length.")
                    return
        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge
            return msg

        async def tracking_send(msg: Message) -> None:
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await _send_json(send, 413, "payload_too_large", "Request body too large.")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope.get("path", "").startswith("/api")
        is_docs = scope.get("path", "").startswith("/api/docs")

        async def send_with_headers(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                headers = list(msg.get("headers", []))
                headers += [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-synthetic-data", b"true"),
                ]
                if is_api and not is_docs:
                    headers.append((b"cache-control", b"no-store"))
                msg["headers"] = headers
            await send(msg)

        await self.app(scope, receive, send_with_headers)


async def _send_json(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message, "details": None}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _sqlite_path(url: str) -> Path | None:
    if url.startswith("sqlite:///") and ":memory:" not in url:
        return Path(url.removeprefix("sqlite:///"))
    return None


def create_app(settings: Settings | None = None, data_dir: Path | None = None) -> FastAPI:
    settings = settings or get_settings()
    db_file = _sqlite_path(settings.database_url)
    if db_file is not None:
        db_file.parent.mkdir(parents=True, exist_ok=True)
    data_dir = data_dir or (db_file.parent if db_file is not None else Path("./data"))
    engine = make_engine(settings.database_url)
    Repository.init_schema(engine)
    repo = Repository(make_session_factory(engine))
    repo.seed_assets()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = SimulationRuntime(settings, repo, data_dir)
        runtime.hub.bind_loop(asyncio.get_running_loop())
        app.state.runtime = runtime
        if settings.autostart:
            await runtime.start()
        try:
            yield
        finally:
            await runtime.shutdown()
            engine.dispose()

    app = FastAPI(
        title="OT Sentinel Twin API",
        version=settings.version,
        description="Physics-based anomaly detection on a fully synthetic industrial digital twin. "
        "All telemetry is simulated; nothing here connects to real industrial equipment.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.repo = repo
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "X-API-Key", "X-Analyst"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            body = detail
        else:
            body = {"code": f"http_{exc.status_code}", "message": str(detail), "details": None}
        return JSONResponse({"error": body}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": details,
                }
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "Internal server error.", "details": None}},
            status_code=500,
        )

    app.include_router(simulation.router)
    app.include_router(data.router)
    app.include_router(ws.router)

    # Optional: serve a built frontend from the same origin (single-process mode).
    dist = Path(os.environ.get("OTST_FRONTEND_DIST", "")) if os.environ.get("OTST_FRONTEND_DIST") else None
    if dist is not None and (dist / "index.html").exists():
        root = dist.resolve()

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            if full_path.startswith(("api/", "ws/")):
                raise HTTPException(404, "Not found")
            candidate = (root / full_path).resolve()
            if full_path and candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(root / "index.html")

    return app


# Run with: uvicorn app.main:create_app --factory
