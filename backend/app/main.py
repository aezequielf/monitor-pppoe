"""Aplicación FastAPI del monitor."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .auth.router import router as auth_router
from .auth.users import init_db
from .config import get_settings
from .monitor.lease import LeaseManager
from .monitor.router import router as monitor_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_for_run()
    init_db()
    manager = LeaseManager(settings)
    manager.start()
    app.state.lease_manager = manager
    try:
        yield
    finally:
        await manager.shutdown()


OPENAPI_TAGS = [
    {"name": "auth", "description": "Login de operadores, refresh y logout."},
    {
        "name": "monitor",
        "description": "Sesión exclusiva (lease), stream SSE y datos del abonado.",
    },
    {"name": "health", "description": "Estado del servicio."},
]

app = FastAPI(
    title="Monitor PPPoE",
    version=__version__,
    description="Monitoreo en tiempo real de sesiones de abonados en un BRAS.",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router)
app.include_router(monitor_router)


@app.get("/api/v1/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


if settings.serve_frontend:
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    _frontend_dir = Path(settings.frontend_dir)
    if _frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
