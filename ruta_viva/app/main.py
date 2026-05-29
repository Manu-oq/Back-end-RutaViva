import logging
import time
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import get_current_user
from app.api.v1.api import api_router
from app.api.v1.endpoints.shared import router as shared_router
import app.db.models  # noqa: F401
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.http_client import close_all as close_http_clients
from app.core.rate_limit import limiter
from app.db.session import get_db, init_db
from app.models.user import User
from slowapi.errors import RateLimitExceeded


logger = logging.getLogger("ruta_viva.telemetry")


@asynccontextmanager
async def lifespan(app: FastAPI):
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()
    yield
    await close_http_clients()


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.state.limiter = limiter
MEDIA_DIR = Path(__file__).resolve().parents[1] / "media"
ALLOWED_MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(shared_router, prefix="/share")


def _resolve_media_path(filename: str) -> Path:
    candidate_name = Path(filename).name
    if (
        not filename
        or candidate_name != filename
        or "/" in filename
        or "\\" in filename
        or Path(filename).suffix.lower() not in ALLOWED_MEDIA_SUFFIXES
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found.")

    candidate_path = (MEDIA_DIR / candidate_name).resolve()
    media_root = MEDIA_DIR.resolve()
    if media_root not in candidate_path.parents:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found.")
    if not candidate_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found.")
    return candidate_path


@app.get("/media/{filename}", tags=["media"])
async def read_media_file(
    filename: str,
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    del current_user
    return FileResponse(_resolve_media_path(filename))


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


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            error=exc.__class__.__name__,
            detail=exc.detail,
        ),
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content=_error_payload(
            error="RateLimitExceeded",
            detail="Has enviado muchos mensajes muy rápido. Espera un momento y vuelve a intentarlo.",
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

    if request.url.path != "/health":
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
