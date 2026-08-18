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

# 예외: 사용자가 버튼으로 명시 요청하는 느린 경로(SMB xlsx 파싱)는 2s 예산을 못 지킨다.
# 폴링이 아니라 1회성 요청이라 api 가 이 시간 묶여도 대시보드 다른 화면에 영향이 없다.
COLLECTOR_SLOW_TIMEOUT_S = 30.0


async def _proxy_collector(
    path: str, if_none_match: str | None, timeout_s: float = COLLECTOR_TIMEOUT_S
) -> Response:
    """Proxy a collector endpoint.

    Forwards ETag/If-None-Match so conditional requests short-circuit to 304, and
    degrades to a fast 503 when the collector profile service is stopped or
    unreachable. The api must never hang or crash because the collector is down —
    the request is capped at a wall-clock budget (2s by default) and any transport
    error or timeout becomes a 503.
    """
    url = f"{settings.COLLECTOR_URL}{path}"
    request_headers = {}
    if if_none_match is not None:
        request_headers["If-None-Match"] = if_none_match

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            upstream = await asyncio.wait_for(
                client.get(url, headers=request_headers),
                timeout=timeout_s,
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


async def _proxy_collector_post(path: str) -> Response:
    """POST 변형 — 작업 시작처럼 부수효과가 있는 호출용. 본문은 쓰지 않는다."""
    try:
        async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT_S) as client:
            upstream = await asyncio.wait_for(
                client.post(f"{settings.COLLECTOR_URL}{path}"),
                timeout=COLLECTOR_TIMEOUT_S,
            )
    except (httpx.HTTPError, asyncio.TimeoutError):
        return JSONResponse(status_code=503, content={"detail": "collector unavailable"})
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
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


@router.get("/lp-eval-ts")
async def get_inav_lp_eval_ts(
    date: str | None = None,
    basis: str | None = None,
    if_none_match: str | None = Header(default=None),
) -> Response:
    """Proxy the collector's LP 평가 인정 스프레드 틱 시계열(분봉, 차트용)."""
    params = []
    if date:
        params.append(f"date={date}")
    if basis:
        params.append(f"basis={basis}")
    suffix = f"?{'&'.join(params)}" if params else ""
    return await _proxy_collector(f"/lp-eval-ts{suffix}", if_none_match)


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


@router.get("/guru-13f/flows")
async def get_guru13f_flows(
    view: str | None = None, if_none_match: str | None = Header(default=None)
) -> Response:
    """Proxy the collector's 거장 변동 분석(동시 리밸런싱·편입/방출·섹터).

    view 생략 시 세 뷰를 한 번에 반환한다. 사전계산분이라 응답이 가볍다.
    """
    path = "/guru-13f/flows" + (f"?view={view}" if view else "")
    return await _proxy_collector(path, if_none_match)


# ── [성과보고] 데일리·위클리 성과 브리프 ─────────────────────────────────
@router.get("/perf-brief")
async def get_perf_brief(if_none_match: str | None = Header(default=None)) -> Response:
    """Proxy the collector's 오늘자 성과보고(월=위클리 / 화~금=데일리) payload."""
    return await _proxy_collector("/perf-brief", if_none_match)


@router.get("/perf-brief/analyze")
async def get_perf_brief_analyze(
    mode: str = "daily", if_none_match: str | None = Header(default=None)
) -> Response:
    """Proxy the collector's 엑셀 실시간 분석([분석 시작] 버튼). mode=daily|weekly."""
    return await _proxy_collector(
        f"/perf-brief/analyze?mode={mode}", if_none_match, COLLECTOR_SLOW_TIMEOUT_S
    )


@router.post("/perf-brief/generate")
async def post_perf_brief_generate(mode: str = "daily") -> Response:
    """Kick off 보고서 생성(Windows 러너의 claude 서브프로세스). 즉시 202 로 돌아온다."""
    return await _proxy_collector_post(f"/perf-brief/generate?mode={mode}")


@router.get("/perf-brief/generate/status")
async def get_perf_brief_generate_status(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """Proxy 보고서 생성 진행상황(러너 작업 상태 + 로그 꼬리)."""
    return await _proxy_collector("/perf-brief/generate/status", if_none_match)


# ── [성과보고 HTML] S: bat 산출물 뷰어 ───────────────────────────────────
@router.get("/perf-report")
async def get_perf_report(if_none_match: str | None = Header(default=None)) -> Response:
    """Proxy 성과보고 HTML 목록 + 오늘치 판정(파일명=기준일 / mtime=작성일).

    목록도 원문과 같은 SMB 경로다 — 작성일 판정에 보고서 파일마다 stat 이 붙고
    건당 ~40ms 라 보고서가 쌓일수록 2s 예산을 넘긴다(실측 29개 2.1s). 넘기는
    순간 카드가 통째로 503 "collector unavailable" 이 되므로 느린 예산을 쓴다.
    """
    return await _proxy_collector(
        "/perf-report", if_none_match, COLLECTOR_SLOW_TIMEOUT_S
    )


@router.get("/perf-report/file")
async def get_perf_report_file(
    path: str = "", if_none_match: str | None = Header(default=None)
) -> Response:
    """Proxy 성과보고 HTML 원문. SMB 읽기라 느린 경로 예산을 쓴다."""
    from urllib.parse import quote

    return await _proxy_collector(
        f"/perf-report/file?path={quote(path)}", if_none_match, COLLECTOR_SLOW_TIMEOUT_S
    )


# ── [누적 수익률 비교] 등록된 펀드 시계열 ────────────────────────────────
@router.get("/fund-series")
async def get_fund_series(if_none_match: str | None = Header(default=None)) -> Response:
    """Proxy 표준 스키마 펀드 시계열(누적수익률% + 리밸 날짜). 펀드 N 개."""
    return await _proxy_collector("/fund-series", if_none_match)


# ── [회의] 회의자료 파일 탐색기 (PoC) ───────────────────────────────────
@router.get("/telegram-news")
async def get_telegram_news(if_none_match: str | None = Header(default=None)) -> Response:
    """[뉴스 모니터링 · 텔레그램] 실시간 카드 피드. 사전계산분이라 응답은 가볍다."""
    return await _proxy_collector("/telegram-news", if_none_match)


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
    """Proxy the collector's 회의자료 HTML 원문(지정 경로).

    사용자가 파일을 고를 때만 도는 1회성 경로라 폴링용 2초 예산을 쓰지 않는다 —
    회의자료에는 20MB 넘는 통합본이 있고(예: Guru_베팅현황.html), collector→api
    전송만 2초 근처라 기본 예산에서는 그대로 503 이 났다(2026-07-29 실제 발생).
    """
    from urllib.parse import quote

    return await _proxy_collector(
        f"/meeting/file?path={quote(path)}", if_none_match, COLLECTOR_SLOW_TIMEOUT_S
    )
