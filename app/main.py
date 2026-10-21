import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import internal, routes
from app.config import get_settings
from app.db import init_db

INDEX_HTML = Path(__file__).parent / "static" / "index.html"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if get_settings().auto_create_tables:
        init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="RepairCalc",
        version="0.1.0",
        description="Микросервис умных калькуляторов ремонта на данных каталога",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"]
    )
    app.include_router(routes.router)
    app.include_router(routes.health_router)
    app.include_router(internal.router)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(INDEX_HTML)

    return app


app = create_app()
