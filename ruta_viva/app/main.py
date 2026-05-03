import logging
import time
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.api import api_router
import app.db.models  # noqa: F401
from app.core.config import settings
from app.db.session import get_db, init_db


logger = logging.getLogger("ruta_viva.telemetry")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
MEDIA_DIR = Path(__file__).resolve().parents[1] / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


def _status_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "HTTP Error"


def _error_payload(error: str, detail: Any) -> dict[str, Any]:
    return {"error": error, "detail": detail}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            error=_status_phrase(exc.status_code),
            detail=exc.detail,
        ),
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            error="Validation Error",
            detail=jsonable_encoder(exc.errors()),
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error while processing %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=_error_payload(
            error=exc.__class__.__name__,
            detail=str(exc) or "Unexpected internal server error.",
        ),
    )


@app.middleware("http")
async def telemetry_middleware(request: Request, call_next) -> Response:
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        process_time_ms = (time.perf_counter() - start_time) * 1000
        logger.exception(
            "%s %s - 500 Internal Server Error - %.0fms",
            request.method,
            request.url.path,
            process_time_ms,
        )
        raise

    process_time_seconds = time.perf_counter() - start_time
    process_time_ms = process_time_seconds * 1000

    response.headers["X-Process-Time"] = f"{process_time_seconds:.6f}"

    status_text = _status_phrase(response.status_code)

    logger.info(
        "%s %s - %s %s - %.0fms",
        request.method,
        request.url.path,
        response.status_code,
        status_text,
        process_time_ms,
    )

    return response


@app.get("/health", tags=["health"])
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "up"}
