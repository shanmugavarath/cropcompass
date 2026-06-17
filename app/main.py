from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import profile, forecast, chat
from pipeline.scheduler import build_scheduler

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────
    scheduler = build_scheduler()
    scheduler.start()
    log.info("scheduler_started", jobs=[j.id for j in scheduler.get_jobs()])
    yield
    # ── Shutdown ──────────────────────────────────────────────
    scheduler.shutdown(wait=False)
    log.info("scheduler_stopped")


app = FastAPI(
    title="CropCompass API",
    description="Multilingual Agentic Advisory System for Indian Farmers",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profile.router)
app.include_router(forecast.router)
app.include_router(chat.router)


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}
