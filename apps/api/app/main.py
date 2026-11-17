import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api import (
    alerts,
    brokerage,
    imports,
    internal,
    jobs,
    portfolio,
    stock_discussion,
    system,
    journal,
    market,
    watchlist,
    seasonality,
    guru,
    earnings_monitor,
    valuechain,
    coverage,
    etf,
    news,
    strategy,
    careers,
)
from app.core.daily_sync import daily_sync_loop
from app.core.seasonality_sync import seasonality_sync_loop
from app.core.ai_snapshot_sync import ai_snapshot_sync_loop
from app.core.sec_sync import sec_sync_loop
from app.core.etf_listing_sync import etf_listing_sync_loop
from app.core.ops_alerts import ops_alert_loop
from app.core.errors import register_exception_handlers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ⚠️테스트(`with TestClient(app)`)도 이 lifespan 을 탄다. 그런데 아래 루프·정리는 테스트 DB 가 아니라
    #   **실제 DB(SessionLocal)** 와 실제 증권사 키를 쓴다 — 커밋마다 도는 make check 가 진짜 동기화·작업 등록을
    #   일으킬 수 있었다(2026-10-05 리뷰에서 발견). conftest 가 이 값을 켠다.
    if os.environ.get("PI_DISABLE_BACKGROUND") == "1":
        yield
        return
    # 이 프로세스 안에서 돌던 동기화가 재시작으로 끊겼으면 RUNNING 행을 닫는다.
    from app.api.brokerage import fail_orphaned_syncs
    from app.db.session import SessionLocal

    # ★2026-10-05 DB 가 느리거나 꺼져 있어도 API 는 떠야 한다 — 정리는 다음 재시작에 미룬다.
    try:
        with SessionLocal() as db:
            fail_orphaned_syncs(db)
    except Exception:  # noqa: BLE001
        logger.warning("시작 시 끊긴 동기화 정리 실패 — 건너뜀", exc_info=True)

    tasks = [
        # 이력 동기화: 영업일 16:30(KST) 이후로 안 돌았으면 따라잡는다.
        # ⚠️브라우저가 아니라 **여기**가 국내 체결이 들어오는 유일한 자동 경로다.
        #   프런트의 자동 동기화는 탭이 열려 있을 때만 돈다.
        asyncio.create_task(daily_sync_loop()),
        # 계절성: 지난달 Yahoo 월말 종가가 비어 있으면 SEASONALITY_APPEND 를 sec_crawl 큐에 넣는다.
        asyncio.create_task(seasonality_sync_loop()),
        asyncio.create_task(sec_sync_loop()),
        # AI Key Data: VS Code·PyPI 는 현재값만 준다 — 오늘(KST) 스냅샷이 없으면 찍는다.
        asyncio.create_task(ai_snapshot_sync_loop()),
        # 국내 ETF 신규상장: 오늘(KST) KRX 목록이 없으면 받는다(+DART 상장 예정). 메모리 캐시.
        asyncio.create_task(etf_listing_sync_loop()),
        # 트립와이어(O1): 멈춘 작업·계속 실패하는 원천·LLM 상한 80%·에스컬레이션 → ops_alert_state(5분).
        asyncio.create_task(ops_alert_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Personal Investment Platform API", version="0.1.0", lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
# 응답 압축 — 밸류체인 분류 섹터(tx-financials 등)가 수백 KB 라서. 전 API 응답에 걸린다.
# ⚠️스트리밍(StreamingResponse·SSE) 엔드포인트가 생기면 압축 버퍼링을 상속하므로 그 경로는 제외할 것.
app.add_middleware(GZipMiddleware, minimum_size=1024)

register_exception_handlers(app)

app.include_router(system.router)
app.include_router(jobs.router)
app.include_router(imports.router)
app.include_router(internal.router)
app.include_router(stock_discussion.router)
app.include_router(watchlist.router)
app.include_router(alerts.router)
app.include_router(market.router)
app.include_router(journal.router)
app.include_router(portfolio.router)
app.include_router(brokerage.router)
app.include_router(seasonality.router)
app.include_router(guru.router)
app.include_router(earnings_monitor.router)
app.include_router(valuechain.router)
app.include_router(coverage.router)
app.include_router(etf.router)
app.include_router(news.router)
app.include_router(strategy.router)
app.include_router(careers.router)
