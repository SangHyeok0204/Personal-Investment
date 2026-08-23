"""[종목 모니터] — KOSPI200 분봉 급등락·이상현상 테이블 프록시.

collector 가 Toss_분봉_모니터 DB(분봉 + universe 통계)를 읽어 만든 payload 를 그대로 나른다.
계산은 전부 collector 쪽이다 — 여기는 ETag 통과와 503 격리만 한다.

★`_proxy_collector` 는 `inav` 에서 가져다 쓴다. macro.py 가 같은 선례다 — 헬퍼 안에
  "httpx 의 timeout 은 DNS 해석을 안 묶는다" 같은 사연이 들어 있어서 복제하면 한쪽만
  고쳐진다. 이름이 `inav` 인 것이 걸리지만, 공용 모듈로 빼려면 macro.py 까지 건드려야
  해서 그 리팩터는 이 기능과 분리한다.
"""
from fastapi import APIRouter, Header, Response

from app.api.inav import _proxy_collector

router = APIRouter(prefix="/api/v1/stock-monitor", tags=["stock-monitor"])


@router.get("")
async def get_stock_monitor(
    day: str | None = None,
    sort: str = "value",
    limit: int = 30,
    if_none_match: str | None = Header(default=None),
) -> Response:
    """급등락·이상현상 테이블 한 장.

    sort: value(거래대금) · change(등락률) · sigma(그 종목 자신의 변동성 대비)
    """
    params = [f"sort={sort}", f"limit={limit}"]
    if day:
        params.append(f"day={day}")
    return await _proxy_collector(f"/stock-monitor?{'&'.join(params)}", if_none_match)


@router.get("/index-strip")
async def get_index_strip(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """상단 지수 스트립 — 나스닥 선물 · KOSPI200 · KOSDAQ150 · S&P500 · 나스닥100.

    원천은 CHECK 에이전트가 분단위로 쌓는 INDEX_MONITOR.db 다. iNAV 화면의 지수 줄과
    같은 DB 를 보지만 대상 지수가 달라(그쪽은 3종) collector 에서 코드 목록을 갈라 뒀다.
    """
    return await _proxy_collector("/index-strip", if_none_match)
