import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api import (
    ai_key_data,
    alerts,
    ai_usage,
    brokerage,
    etf_class,
    imports,
    inav,
    internal,
    jobs,
    lan,
    macro,
    portfolio,
    stock_discussion,
    system,
    journal,
    market,
    watchlist,
    seasonality,
    guru,
    insiders,
    earnings_monitor,
    valuechain,
    coverage,
)
from app.core.daily_sync import daily_sync_loop
from app.core.seasonality_sync import seasonality_sync_loop
from app.core.ai_snapshot_sync import ai_snapshot_sync_loop
from app.core.sec_sync import sec_sync_loop
from app.core.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [
        # LAN 대시보드: 30초 주기로 서버 상태를 폴링하는 백그라운드 체커.
        asyncio.create_task(lan.background_checker_loop()),
        # 이력 동기화: 영업일 16:30(KST) 이후로 안 돌았으면 따라잡는다.
        # ⚠️브라우저가 아니라 **여기**가 국내 체결이 들어오는 유일한 자동 경로다.
        #   프런트의 자동 동기화는 탭이 열려 있을 때만 돈다.
        asyncio.create_task(daily_sync_loop()),
        # 계절성: 지난달 Yahoo 월말 종가가 비어 있으면 SEASONALITY_APPEND 를 sec_crawl 큐에 넣는다.
        asyncio.create_task(seasonality_sync_loop()),
        asyncio.create_task(sec_sync_loop()),
        # AI Key Data: VS Code·PyPI 는 현재값만 준다 — 오늘(KST) 스냅샷이 없으면 찍는다.
        asyncio.create_task(ai_snapshot_sync_loop()),
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
app.include_router(ai_usage.router)
app.include_router(inav.router)
app.include_router(macro.router)
app.include_router(lan.router)
app.include_router(stock_discussion.router)
app.include_router(ai_key_data.router)
# [AI Key Data] 카드 3개는 경로만 옛 `/api/v1/stock-monitor` 프리픽스에 남아 있다
# (ai_key_data.py 의 `legacy_router` 주석 참조).
app.include_router(ai_key_data.legacy_router)
app.include_router(watchlist.router)
app.include_router(alerts.router)
app.include_router(market.router)
app.include_router(journal.router)
app.include_router(etf_class.router)
app.include_router(portfolio.router)
app.include_router(brokerage.router)
app.include_router(seasonality.router)
app.include_router(guru.router)
app.include_router(insiders.router)
app.include_router(earnings_monitor.router)
app.include_router(valuechain.router)
app.include_router(coverage.router)
