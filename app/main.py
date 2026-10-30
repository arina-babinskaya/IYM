import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import catalog_admin, consultant, decor, picker, routes
from app.config import get_settings
from app.db import init_db

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"

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
    app.include_router(catalog_admin.router)
    app.include_router(picker.router)
    app.include_router(decor.router)
    app.include_router(consultant.router)
    app.include_router(routes.health_router)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        # The consultant is plain JavaScript embedded in this document. Always revalidate the
        # shell so deployments cannot leave a browser running an older request lifecycle against
        # a newer backend. Fingerprinted static asset URLs in the shell remain cacheable.
        return FileResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
