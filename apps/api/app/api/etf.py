"""국내 ETF 신규상장 — `core/etf_listing_sync` 캐시를 그대로 내보낸다(외부 호출 없음).

★캐시가 아직 비어 있어도(기동 직후·키 미설정) **200 + note** 다. 503 을 내면 화면이
  "불러오지 못했다"와 "상장이 없다"를 가를 수 없다 — note 가 그 차이를 말한다.
"""
from fastapi import APIRouter

from app.core import etf_listing_sync

router = APIRouter(prefix="/api/v1/etf", tags=["etf"])


@router.get("/new-listing")
def get_new_listing() -> dict:
    return etf_listing_sync.payload()
