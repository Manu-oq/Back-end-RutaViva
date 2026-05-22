from __future__ import annotations

import httpx

_clients: dict[str, httpx.AsyncClient] = {}


def get_client(name: str, base_url: str | None = None, timeout: float = 15.0) -> httpx.AsyncClient:
    if name not in _clients:
        _clients[name] = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _clients[name]


async def close_all() -> None:
    for name, client in _clients.items():
        try:
            await client.aclose()
        except Exception:
            pass
    _clients.clear()