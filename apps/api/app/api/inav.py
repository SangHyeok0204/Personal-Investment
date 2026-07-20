import asyncio

import httpx
from fastapi import APIRouter, Header, Response
from fastapi.responses import JSONResponse

from app.core.config import settings

router = APIRouter(prefix="/api/v1/inav", tags=["inav"])

# Hard wall-clock budget for the whole proxied call. httpx's own timeout only
# bounds the connect/read/write phases, not DNS resolution (getaddrinfo) — when
# the collector container is stopped, its hostname can take several seconds to
# fail to resolve. asyncio.wait_for enforces the ≤2s budget regardless of where
# the upstream call is stuck.
COLLECTOR_TIMEOUT_S = 2.0


async def _proxy_collector(path: str, if_none_match: str | None) -> Response:
    """Proxy a collector endpoint.

    Forwards ETag/If-None-Match so conditional requests short-circuit to 304, and
    degrades to a fast 503 when the collector profile service is stopped or
    unreachable. The api must never hang or crash because the collector is down —
    the request is capped at a 2s wall-clock budget and any transport error or
    timeout becomes a 503.
    """
    url = f"{settings.COLLECTOR_URL}{path}"
    request_headers = {}
    if if_none_match is not None:
        request_headers["If-None-Match"] = if_none_match

    try:
        async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT_S) as client:
            upstream = await asyncio.wait_for(
                client.get(url, headers=request_headers),
                timeout=COLLECTOR_TIMEOUT_S,
            )
    except (httpx.HTTPError, asyncio.TimeoutError):
        return JSONResponse(status_code=503, content={"detail": "collector unavailable"})

    passthrough_headers = {}
    etag = upstream.headers.get("ETag")
    if etag:
        passthrough_headers["ETag"] = etag

    if upstream.status_code == 304:
        return Response(status_code=304, headers=passthrough_headers)

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
        headers=passthrough_headers,
    )


@router.get("/snapshot")
async def get_inav_snapshot(if_none_match: str | None = Header(default=None)) -> Response:
    """Proxy the collector's iNAV snapshot."""
    return await _proxy_collector("/snapshot", if_none_match)


@router.get("/components")
async def get_inav_components(if_none_match: str | None = Header(default=None)) -> Response:
    """Proxy the collector's per-ETF components payload (구성종목 모달/무버 티커)."""
    return await _proxy_collector("/components", if_none_match)


@router.get("/wrap")
async def get_inav_wrap(if_none_match: str | None = Header(default=None)) -> Response:
    """Proxy the collector's WRAP portfolio realtime-return payload."""
    return await _proxy_collector("/wrap", if_none_match)


@router.get("/hoga")
async def get_inav_hoga(if_none_match: str | None = Header(default=None)) -> Response:
    """Proxy the collector's CHECK-agent 호가(orderbook) envelope for the web card UI."""
    return await _proxy_collector("/hoga", if_none_match)
