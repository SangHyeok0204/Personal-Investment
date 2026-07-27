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


@router.get("/index-window")
async def get_inav_index_window(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """Proxy the collector's 지수 롤링 60분 변동폭(max−min) 통계 (알림 팝업용)."""
    return await _proxy_collector("/index-window", if_none_match)


@router.get("/index-alerts")
async def get_inav_index_alerts(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """Proxy the collector's 지수 급등락 하루 알림 로그(서버측 계산, 전 클라이언트 동일)."""
    return await _proxy_collector("/index-alerts", if_none_match)


@router.get("/lp-eval")
async def get_inav_lp_eval(
    date: str | None = None,
    basis: str | None = None,
    if_none_match: str | None = Header(default=None),
) -> Response:
    """Proxy the collector's LP 평가(인정 스프레드 틱 체류시간 분포·통계)."""
    params = []
    if date:
        params.append(f"date={date}")
    if basis:
        params.append(f"basis={basis}")
    suffix = f"?{'&'.join(params)}" if params else ""
    return await _proxy_collector(f"/lp-eval{suffix}", if_none_match)


@router.get("/wrap-performance")
async def get_inav_wrap_performance(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """Proxy the collector's WRAP 성과 비교(자사 vs TORUS 누적수익률) 시계열."""
    return await _proxy_collector("/wrap-performance", if_none_match)


@router.get("/wrap-rebalancing")
async def get_inav_wrap_rebalancing(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """Proxy the collector's 리밸런싱 이력(자사·TORUS 시점별 편입 구성)."""
    return await _proxy_collector("/wrap-rebalancing", if_none_match)


# ── GURU[13F] track record ──────────────────────────────────────────────
# collector 가 13F 거장 포트폴리오 비중/변화 payload 를 서빙(로컬 .cache 스냅샷).
# 전부 기존 _proxy_collector 재사용 — ETag/304 pass-through. 쿼리스트링은 그대로 전달.


@router.get("/guru-13f/roster")
async def get_guru13f_roster(if_none_match: str | None = Header(default=None)) -> Response:
    """Proxy the collector's GURU[13F] 로스터(최신분기 제출 거장 + 분기 목록)."""
    return await _proxy_collector("/guru-13f/roster", if_none_match)


@router.get("/guru-13f/portfolio")
async def get_guru13f_portfolio(
    cik: str, period: str, if_none_match: str | None = Header(default=None)
) -> Response:
    """Proxy the collector's 거장 1곳·분기 포트폴리오 구성(top-N 보유·AUM·집중도)."""
    return await _proxy_collector(f"/guru-13f/portfolio?cik={cik}&period={period}", if_none_match)


@router.get("/guru-13f/changes")
async def get_guru13f_changes(
    cik: str, period: str, if_none_match: str | None = Header(default=None)
) -> Response:
    """Proxy the collector's QoQ 비중 변화(신규/청산/확대/축소)."""
    return await _proxy_collector(f"/guru-13f/changes?cik={cik}&period={period}", if_none_match)


@router.get("/guru-13f/timeline")
async def get_guru13f_timeline(
    cik: str, if_none_match: str | None = Header(default=None)
) -> Response:
    """Proxy the collector's 거장 top-N 종목 분기별 비중 추이."""
    return await _proxy_collector(f"/guru-13f/timeline?cik={cik}", if_none_match)


@router.get("/guru-13f/consensus")
async def get_guru13f_consensus(
    period: str | None = None, if_none_match: str | None = Header(default=None)
) -> Response:
    """Proxy the collector's 거장 컨센서스(교차 보유·공동 매수/매도, 최신분기 사전계산)."""
    path = "/guru-13f/consensus" + (f"?period={period}" if period else "")
    return await _proxy_collector(path, if_none_match)


@router.get("/guru-13f/turnover")
async def get_guru13f_turnover(
    period: str | None = None, if_none_match: str | None = Header(default=None)
) -> Response:
    """Proxy the collector's 거장 턴오버 리더보드(최신분기 사전계산)."""
    path = "/guru-13f/turnover" + (f"?period={period}" if period else "")
    return await _proxy_collector(path, if_none_match)


# ── [회의] 회의자료 파일 탐색기 (PoC) ───────────────────────────────────
@router.get("/meeting/list")
async def get_meeting_list(
    path: str = "", if_none_match: str | None = Header(default=None)
) -> Response:
    """Proxy the collector's 회의자료 폴더 목록(하위 폴더 + HTML)."""
    from urllib.parse import quote

    return await _proxy_collector(f"/meeting/list?path={quote(path)}", if_none_match)


@router.get("/meeting/file")
async def get_meeting_file(
    path: str, if_none_match: str | None = Header(default=None)
) -> Response:
    """Proxy the collector's 회의자료 HTML 원문(지정 경로)."""
    from urllib.parse import quote

    return await _proxy_collector(f"/meeting/file?path={quote(path)}", if_none_match)
