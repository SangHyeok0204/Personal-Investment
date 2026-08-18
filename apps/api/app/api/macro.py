"""매크로 패널 프록시 — collector 의 /macro/panels 를 그대로 넘긴다 (2026-08-13).

근거는 S: 매크로모니터가 구운 macro_panels.json(FRED/BLS/CME). api 는 계산하지 않는다.
프록시 규약(타임아웃 예산·ETag 통과·collector 정지 시 503)은 inav 와 동일하다.
"""
from fastapi import APIRouter, Header, Response

from app.api.inav import _proxy_collector

router = APIRouter(prefix="/api/v1/macro", tags=["macro"])


@router.get("/panels")
async def macro_panels(if_none_match: str | None = Header(default=None)) -> Response:
    return await _proxy_collector("/macro/panels", if_none_match)
