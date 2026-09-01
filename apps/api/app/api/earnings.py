"""[종목 모니터링] 어닝 프록시 — collector 의 `/earnings` 를 그대로 넘긴다 (2026-09-01).

근거는 S: 어닝모니터 daily-server 가 굽는 마스터 원장(`보유종목정리.xlsx`)이다.
api 는 계산하지 않는다. 프록시 규약(타임아웃 예산·ETag 통과·collector 정지 시 503)은
inav·macro 와 동일하다.

경로에 `/us` 를 박아 둔 것은 한국·중국 탭이 같은 배선을 이어받을 자리를 비워 두기
위해서다 — 그때는 collector 쪽에 시장 인자를 더하고 여기에 라우트 한 줄을 붙인다.
"""
from fastapi import APIRouter, Header, Response

from app.api.inav import _proxy_collector

router = APIRouter(prefix="/api/v1/earnings", tags=["earnings"])


@router.get("/us")
async def earnings_us(if_none_match: str | None = Header(default=None)) -> Response:
    return await _proxy_collector("/earnings", if_none_match)


@router.get("/us/issues")
async def stock_issues_us(if_none_match: str | None = Header(default=None)) -> Response:
    """이슈 모니터 — 같은 상류(어닝모니터)의 stock_issue_alert 일간 리포트."""
    return await _proxy_collector("/stock-issue", if_none_match)
