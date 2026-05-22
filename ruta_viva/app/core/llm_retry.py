import asyncio
import logging
from typing import TypeVar, Callable, Awaitable

import httpx

logger = logging.getLogger(__name__)
T = TypeVar("T")

RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    httpx.HTTPStatusError,
)


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    max_retries: int = 2,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    operation_name: str = "llm_call",
) -> T:
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except RETRYABLE_EXCEPTIONS as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                raise
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    f"{operation_name} attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
        except Exception:
            raise

    raise last_exception  # type: ignore
