import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api import routes_caller, routes_operator
from app.api.events import bus
from app.config import get_settings
from app.gnani import http as gnani_http
from app.logging_utils import setup_logging
from app.queue.store import store
from app.security import BodySizeLimit, SecurityHeaders, inline_script_hashes

STATIC = Path(__file__).resolve().parent.parent / "static"
REORDER_TICK_S = 15


async def _reorder_loop() -> None:
    """Waiting time alone can make a review item overdue; re-rank (and audit) on a timer."""
    while True:
        await asyncio.sleep(REORDER_TICK_S)
        moved = store.reorder()
        if moved:
            bus.publish("queue_reordered", {"changes": [e.model_dump() for e in moved]})


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    task = asyncio.create_task(_reorder_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await gnani_http.aclose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.APP_NAME, lifespan=lifespan, docs_url="/docs" if s.ENABLE_DOCS else None,
                  redoc_url=None, openapi_url="/openapi.json" if s.ENABLE_DOCS else None)
    app.include_router(routes_caller.router)
    app.include_router(routes_operator.router)
    # outermost first: size limit runs before anything reads the body
    app.add_middleware(SecurityHeaders,
                       script_hashes=inline_script_hashes(STATIC / "caller.html", STATIC / "operator.html"))
    app.add_middleware(BodySizeLimit)

    @app.get("/", include_in_schema=False)
    async def caller() -> FileResponse:
        return FileResponse(STATIC / "caller.html", media_type="text/html; charset=utf-8")

    @app.get("/operator", include_in_schema=False)
    async def operator() -> FileResponse:
        return FileResponse(STATIC / "operator.html", media_type="text/html; charset=utf-8")

    return app


app = create_app()
