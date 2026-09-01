"""[종목 모니터] — KOSPI200 분봉 급등락·이상현상 테이블 프록시.

collector 가 Toss_분봉_모니터 DB(분봉 + universe 통계)를 읽어 만든 payload 를 그대로 나른다.
계산은 전부 collector 쪽이다 — 여기는 ETag 통과와 503 격리만 한다.

★`_proxy_collector` 는 `inav` 에서 가져다 쓴다. macro.py 가 같은 선례다 — 헬퍼 안에
  "httpx 의 timeout 은 DNS 해석을 안 묶는다" 같은 사연이 들어 있어서 복제하면 한쪽만
  고쳐진다. 이름이 `inav` 인 것이 걸리지만, 공용 모듈로 빼려면 macro.py 까지 건드려야
  해서 그 리팩터는 이 기능과 분리한다.
"""
import asyncio
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Body, Header, Response
from fastapi.responses import JSONResponse

from app.api.inav import COLLECTOR_SLOW_TIMEOUT_S, _proxy_collector
from app.core.config import settings

router = APIRouter(prefix="/api/v1/stock-monitor", tags=["stock-monitor"])


@router.get("")
async def get_stock_monitor(
    day: str | None = None,
    sort: str = "value",
    limit: int = 30,
    market: str = "kr",
    if_none_match: str | None = Header(default=None),
) -> Response:
    """급등락·이상현상 테이블 한 장.

    sort: value(거래대금) · change(등락률) · sigma(그 종목 자신의 변동성 대비)
    market: kr(KOSPI200 분봉) · us(미장 실시간 체결 — 미장_실시간체결가.db lane)
    """
    params = [f"sort={sort}", f"limit={limit}", f"market={market}"]
    if day:
        params.append(f"day={day}")
    return await _proxy_collector(f"/stock-monitor?{'&'.join(params)}", if_none_match)


@router.get("/stock-detail")
async def get_stock_detail(
    name: str,
    if_none_match: str | None = Header(default=None),
) -> Response:
    """종목 상세 — stock_info(sector·country·currency) + stock_axis(5대 축) 병합."""
    return await _proxy_collector(
        f"/stock-monitor/stock-detail?name={quote(name)}", if_none_match
    )


@router.post("/stock-axis")
async def post_stock_axis(payload: dict = Body(...)) -> Response:
    """5대 축 저장 — 본문을 그대로 collector 로 나른다.

    inav 의 `_proxy_collector_post` 는 본문을 안 실어(작업 트리거 전용) 못 쓴다.
    타임아웃은 SLOW 예산 — 목적지가 SMB(S:) 파일이라 2s 를 못 지킬 수 있고,
    폴링이 아니라 저장 버튼 1회성이라 묶여도 다른 화면에 영향이 없다.
    """
    try:
        async with httpx.AsyncClient(timeout=COLLECTOR_SLOW_TIMEOUT_S) as client:
            upstream = await asyncio.wait_for(
                client.post(
                    f"{settings.COLLECTOR_URL}/stock-monitor/stock-axis", json=payload
                ),
                timeout=COLLECTOR_SLOW_TIMEOUT_S,
            )
    except (httpx.HTTPError, asyncio.TimeoutError):
        return JSONResponse(status_code=503, content={"detail": "collector unavailable"})
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


@router.get("/market-signal")
async def get_market_signal(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[시장 시그널] AI 판단 급등락 — ETF 순매수 카드 자리(2026-08-31 교체).

    1단 결정론 룰 → 2단 온톨로지 탐색 → 3단 뉴스 근거. 계산은 전부 collector.
    ★뉴스 조회가 붙어 실측 5~7초다 → 기본 2초 예산이 아니라 SLOW 예산을 쓴다.
    """
    return await _proxy_collector("/market-signal", if_none_match,
                                  COLLECTOR_SLOW_TIMEOUT_S)


@router.get("/etf-flows")
async def get_etf_flows(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[ETF 순매수 모니터] — 관심 ETF(주로 신규상장)의 거래대금·거래량·개인 순매수.

    원천은 CHECK 에이전트가 적재하는 ETF_FLOW_MONITOR.db (INDEX_MONITOR 와 같은
    S: _데이터베이스 폴더). 적재가 시작되기 전에는 rows 가 빈 배열로 온다.
    """
    return await _proxy_collector("/etf-flows", if_none_match)


@router.get("/index-strip")
async def get_index_strip(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """상단 지수 스트립 — 나스닥 선물 · KOSPI200 · KOSDAQ150 · S&P500 · 나스닥100.

    원천은 CHECK 에이전트가 분단위로 쌓는 INDEX_MONITOR.db 다. iNAV 화면의 지수 줄과
    같은 DB 를 보지만 대상 지수가 달라(그쪽은 3종) collector 에서 코드 목록을 갈라 뒀다.
    """
    return await _proxy_collector("/index-strip", if_none_match)


@router.get("/price-returns")
async def get_price_returns(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[수익률 모니터] — 관심 자산(금·비트코인·30년 국채금리)의 YtD·MtD·WtD·DtD +
    저점 대비 상승 + 1년 스파크.

    원천은 주간가격모니터의 price_monitor.xlsx (S: 마운트, collector 가 mtime 캐시로
    판독). 자산 목록의 정본은 collector price_returns.ASSETS.
    """
    return await _proxy_collector("/price-returns", if_none_match)


@router.get("/compute-index")
async def get_compute_index(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[컴퓨팅 지수 모니터링] — GPU 렌탈 지수 3분할(H100 · B200 · B200/H100 배수).

    원천은 AI Key Data의 GPU임대지수_주가_통합.xlsx (블룸버그 내보내기).
    지수 목록의 정본은 collector compute_index.INDICES.
    """
    return await _proxy_collector("/compute-index", if_none_match)


@router.get("/policy-rate")
async def get_policy_rate(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[정책금리] — FOMC 금리 결정(수준 %) 시계열.

    원천은 AI Key Data의 macro_releases.csv 중 event=RATE 행. 회의와 회의
    사이엔 금리가 유지되므로 화면은 계단으로 그린다(payload 는 결정 시점만 담는다).
    """
    return await _proxy_collector("/policy-rate", if_none_match)


@router.get("/rate-topics")
async def get_rate_topics(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[금리 5주제] — 하이퍼스케일러 채권발행 · 인플레지표 · WTI · ADP · FOMC 내재확률.

    원천은 AI Key Data 의 `input/raw/금리/금리_2.xlsx` 한 장(신상품팀 공모손차 데이터
    사본). 다섯 카드가 같은 파일을 보므로 엔드포인트도 하나로 둔다 — 주제별로 나누면
    같은 1.6MB 워크북을 다섯 번 연다.
    """
    return await _proxy_collector("/rate-topics", if_none_match)


@router.get("/price-board")
async def get_price_board(
    cat: str = "equity",
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[가격 모니터] — 84개 시장의 Price·DtD·WtD·MtD·YtD + 롤링 1M·3M·6M·1Y.

    cat: equity(주식 42) · bond(채권 17) · commodity(원자재 14) · fx(환 5) · crypto(암호화폐 6)
    분류·지표 정의의 정본은 collector price_board.py (회의자료 생성기에서 이식).
    ★채권은 % 가 아니라 bp 로 온다(payload 의 `is_yield`·`unit` 참조).
    ★rows 의 이 8개 값이 화면 우하단 요약 표를 그대로 채운다(2026-08-31).
    """
    return await _proxy_collector(f"/price-board?cat={quote(cat)}", if_none_match)


@router.get("/price-board/metric-series")
async def get_price_metric_series(
    key: str,
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[가격 모니터] 시장 하나의 차트 계열 — 가격 원본 + 롤링 3M **시계열**.

    ★2026-08-31: DtD·WtD·MtD·YtD 시계열은 뺐다(달력 앵커라 리셋 톱니). 누적수익률·
      벤치마크 대비는 보는 구간에 따라 기준점이 달라져 **프론트가** 가격에서 만든다.
    목록(price-board)과 달리 클릭할 때 하나씩 받는다.
    """
    return await _proxy_collector(
        f"/price-board/metric-series?key={quote(key)}", if_none_match
    )


@router.get("/price-board/group-series")
async def get_price_group_series(
    cat: str = "equity",
    l1: str = "",
    l2: str = "",
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[가격 모니터] 묶음(예: DM/미국) 안 시장들의 차트 계열.

    metric-series 와 payload 모양이 같다 — 계열이 1개냐 N개냐만 다르다.
    목록에서 layer2 를 누르면 이걸 받아 겹쳐 그린다.
    ★`metric` 파라미터는 2026-08-31 삭제 — 계열마다 price·r3m 을 둘 다 실어서
      모드를 바꿔도 재요청이 없다.
    """
    return await _proxy_collector(
        f"/price-board/group-series?cat={quote(cat)}&l1={quote(l1)}&l2={quote(l2)}",
        if_none_match,
    )
