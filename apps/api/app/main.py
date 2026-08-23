import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    ai_usage,
    imports,
    inav,
    internal,
    jobs,
    lan,
    macro,
    stock_discussion,
    stock_monitor,
    system,
)
from app.core.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # LAN 대시보드: 30초 주기로 서버 상태를 폴링하는 백그라운드 체커.
    checker = asyncio.create_task(lan.background_checker_loop())
    try:
        yield
    finally:
        checker.cancel()
        try:
            await checker
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Personal Investment Platform API", version="0.1.0", lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        # 소비 PC(사내 LAN)가 서버 IP로 접속할 때의 오리진
        "http://192.168.199.63:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(stock_monitor.router)
