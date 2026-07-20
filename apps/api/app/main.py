from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ai_usage, imports, inav, internal, jobs, system
from app.core.errors import register_exception_handlers

app = FastAPI(title="Personal Investment Platform API", version="0.1.0")

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
