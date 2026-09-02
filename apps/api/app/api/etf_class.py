"""[국내상장 ETF] 분류별 개인순매수·수익률 프록시.

collector 가 `국내상장ETF 모니터링.xlsm` 의 value 시트를 읽어 만든 payload 를 그대로
나른다. 계산은 전부 collector 쪽이다 — 여기는 ETag 통과와 503 격리만 한다.

`_proxy_collector` 를 inav 에서 가져다 쓰는 건 stock_monitor·macro 와 같은 선례다
(헬퍼 안에 "httpx 의 timeout 은 DNS 해석을 안 묶는다" 같은 사연이 들어 있어 복제하면
한쪽만 고쳐진다).

⚠️타임아웃이 SLOW 예산인 이유: 원천이 SMB(S:) 위의 900행 xlsm 이라 캐시가 식은
   첫 호출이 기본 2초를 넘긴다. 이후에는 mtime 캐시로 즉답한다.
"""
from fastapi import APIRouter, Header, Response

from app.api.inav import COLLECTOR_SLOW_TIMEOUT_S, _proxy_collector

router = APIRouter(prefix="/api/v1/etf-class", tags=["etf-class"])


@router.get("")
async def get_etf_class(if_none_match: str | None = Header(default=None)) -> Response:
    """오늘의 분류별 자금·수익률 한 장 — 축 5개 × 기간 9개를 한 묶음에 담아 온다."""
    return await _proxy_collector("/etf-class", if_none_match, COLLECTOR_SLOW_TIMEOUT_S)


@router.get("/new-listing")
async def get_etf_new_listing(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """신규상장 세 갈래 — 성적표(daily_analysis txt) · 금일 상장(KRX) · 상장 임박(DART).

    ⚠️SLOW 예산인 이유가 다른 엔드포인트와 다르다. 여기는 SMB 판독뿐 아니라 **KRX 목록
      조회(1,167행)** 가 섞여 있다. collector 가 6시간 캐시를 두지만 캐시가 식은 첫
      호출은 로그인+조회로 수 초가 걸린다.
    """
    return await _proxy_collector(
        "/etf-new-listing", if_none_match, COLLECTOR_SLOW_TIMEOUT_S
    )


@router.get("/history")
async def get_etf_class_history(
    axis: str = "mid",
    metric: str = "net",
    period: str = "3m",
    days: int = 400,
    if_none_match: str | None = Header(default=None),
) -> Response:
    """시점별 추이 — collector 가 쌓아 온 스냅샷 이력.

    metric: net(개인 순매수) · ret(수익률) · mcap(시총) / period: d·1w·1m·3m·6m
    """
    return await _proxy_collector(
        f"/etf-class/history?axis={axis}&metric={metric}&period={period}&days={days}",
        if_none_match,
        COLLECTOR_SLOW_TIMEOUT_S,
    )
