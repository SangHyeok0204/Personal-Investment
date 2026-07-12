from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import imports, internal, jobs, system
from app.core.errors import register_exception_handlers

app = FastAPI(title="Personal Investment Platform API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(system.router)
app.include_router(jobs.router)
app.include_router(imports.router)
app.include_router(internal.router)
